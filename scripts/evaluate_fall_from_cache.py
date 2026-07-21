"""scripts/cache_fall_signals.py가 만든 캐시를 재생해 평가한다.

YOLO pose/보조 모델 추론은 전혀 하지 않는다 — 캐시된 Track과 원본 detection을
그대로 읽어 `evaluate_fall.py`의 `score_video_from_frame_source()`(실제 영상
평가와 완전히 같은 채점 경로)로 넘긴다. 상태머신 설정(FallDetectorConfig)이나
--fall-model-iou-threshold를 바꿔가며 반복 실행해도 매번 몇 초~몇 분이 아니라
캐시 읽기 시간만 든다.

Track ID 할당이 재현 가능한지는 캐시를 만들 때(scripts/cache_fall_signals.py)
이미 결정된다. 다만 holdout 가드는 캐시를 한 번 만들면 이후 실행에서 원본
영상 경로를 다시 안 거치므로, 이 스크립트도 캐시 디렉터리의 manifest.json에
기록된 split/videos_dir로 매번 다시 확인한다 — 그러지 않으면 캐시를
복사하거나 재사용해서 Subject 9~10을 별도 승인 없이 반복 평가할 수 있다.

Usage:
    .venv/bin/python scripts/evaluate_fall_from_cache.py \
        --annotations data/annotations/caucafall_v5/development_annotations_v2.csv \
        --cache-dir outputs/fall_eval/cache/pose_conf05_fallv1 \
        --split development \
        --config configs/fall_detection.json \
        --output outputs/fall_eval/development_from_cache.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import fall_signal_cache as cache  # noqa: E402
from evaluate_fall import (  # noqa: E402
    _AnnotationRow,
    _VideoResult,
    _summarize,
    find_excluded_rows,
    guard_holdout,
    load_annotations,
    resolve_video_path,
    score_video_from_frame_source,
    validate_annotations,
    video_result_to_dict,
)

from src.common.types import TrackingResult  # noqa: E402
from src.safety.fall_detector import FallDetectorConfig  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--annotations", required=True, help="annotation CSV 경로")
    parser.add_argument("--cache-dir", required=True, help="scripts/cache_fall_signals.py 출력")
    parser.add_argument(
        "--split",
        default="",
        help="캐시 manifest의 split과 대조·holdout 가드에도 쓰인다(결과 JSON에도 기록됨)",
    )
    parser.add_argument("--config", default="configs/fall_detection.json")
    parser.add_argument("--early-tolerance-sec", type=float, default=0.2)
    parser.add_argument("--timely-window-sec", type=float, default=2.0)
    parser.add_argument("--fall-model-iou-threshold", type=float, default=0.3)
    parser.add_argument("--output", default="outputs/fall_eval/from_cache_summary.json")
    parser.add_argument("--include-unreviewed", action="store_true")
    parser.add_argument(
        "--allow-holdout",
        action="store_true",
        help="캐시 manifest의 split/videos_dir이 holdout이어도 명시적으로 허용한다.",
    )
    return parser.parse_args()


def _frame_source_from_cache(cached_frames, video_id: str):
    for cached_frame in cached_frames:
        tracking_result = TrackingResult(
            frame_number=cached_frame.frame_number,
            timestamp=cached_frame.timestamp,
            video_source=video_id,
            tracks=cached_frame.tracks,
        )
        yield cached_frame.frame_number, tracking_result, cached_frame.raw_detections


def _validate_cache_metadata(
    metadata: dict, manifest: dict, row: _AnnotationRow, videos_dir: Path
) -> Optional[str]:
    """개별 캐시 파일의 메타데이터가 디렉터리 manifest·annotation과 일치하는지 확인한다.

    캐시 파일 하나가 다른 디렉터리에서 잘못 복사되거나 섞여 들어왔을 때,
    schema/video_id 검증(fall_signal_cache.read_video_cache)만으로는 못 잡는다
    — tracker/보조 모델 설정이나 원본 영상 자체가 manifest와 달라도 스키마는
    똑같이 유효하기 때문이다.

    일치하면 None, 아니면 사람이 읽을 첫 번째 불일치 사유 문자열을 반환한다.
    """
    if metadata["tracker"] != manifest["tracker"]:
        return (
            f"{row.video_id}: 캐시의 tracker 설정이 manifest와 다릅니다 "
            f"(캐시={metadata['tracker']}, manifest={manifest['tracker']})"
        )
    if metadata["auxiliary_model"] != manifest["auxiliary_model"]:
        return (
            f"{row.video_id}: 캐시의 auxiliary_model 설정이 manifest와 다릅니다 "
            f"(캐시={metadata['auxiliary_model']}, manifest={manifest['auxiliary_model']})"
        )

    expected_video_path = str(resolve_video_path(row, videos_dir))
    cached_video_path = metadata.get("video_path")
    if cached_video_path is not None and cached_video_path != expected_video_path:
        return (
            f"{row.video_id}: 캐시의 video_path가 annotation이 가리키는 경로와 다릅니다 "
            f"(캐시={cached_video_path}, 기대={expected_video_path})"
        )

    cached_size = metadata.get("video_size_bytes")
    if cached_size is not None and cached_video_path is not None:
        video_file = Path(cached_video_path)
        if video_file.is_file() and video_file.stat().st_size != cached_size:
            return (
                f"{row.video_id}: 원본 영상 크기가 캐싱 당시와 다릅니다 "
                f"(캐시={cached_size}bytes, 현재={video_file.stat().st_size}bytes) — "
                "원본이 바뀌었을 수 있어 캐시를 신뢰할 수 없습니다."
            )

    return None


def _evaluate_row_from_cache(
    row: _AnnotationRow,
    cache_dir: Path,
    manifest: dict,
    videos_dir: Path,
    config: FallDetectorConfig,
    fall_config_path: str,
    early_tolerance_sec: float,
    timely_window_sec: float,
    fall_model_iou_threshold: float,
) -> _VideoResult:
    cache_file = cache.cache_path_for(cache_dir, row.video_id)
    if not cache_file.exists():
        return _VideoResult(
            video_id=row.video_id,
            label=row.label,
            event_count=0,
            error=f"캐시 없음: {cache_file} (scripts/cache_fall_signals.py로 먼저 생성)",
        )

    try:
        metadata, frames = cache.read_video_cache(cache_file, expected_video_id=row.video_id)
    except ValueError as exc:
        return _VideoResult(video_id=row.video_id, label=row.label, event_count=0, error=str(exc))

    mismatch = _validate_cache_metadata(metadata, manifest, row, videos_dir)
    if mismatch is not None:
        return _VideoResult(video_id=row.video_id, label=row.label, event_count=0, error=mismatch)

    fps = metadata["fps"]
    frame_source = _frame_source_from_cache(frames, row.video_id)
    return score_video_from_frame_source(
        row,
        frame_source,
        fps,
        config,
        fall_config_path=fall_config_path,
        fall_model_iou_threshold=fall_model_iou_threshold,
        early_tolerance_sec=early_tolerance_sec,
        timely_window_sec=timely_window_sec,
    )


def main() -> None:
    args = parse_args()

    if args.timely_window_sec <= 0:
        raise SystemExit(f"--timely-window-sec는 0보다 커야 합니다: {args.timely_window_sec}")
    if args.early_tolerance_sec < 0:
        raise SystemExit(f"--early-tolerance-sec는 0 이상이어야 합니다: {args.early_tolerance_sec}")

    config = FallDetectorConfig.from_file(args.config)
    try:
        rows = load_annotations(args.annotations, include_unreviewed=args.include_unreviewed)
        excluded_rows = find_excluded_rows(
            args.annotations, include_unreviewed=args.include_unreviewed
        )
        if not rows:
            raise ValueError("평가할 annotation 행이 없습니다 (review_status='reviewed' 확인).")
        validate_annotations(rows)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    cache_dir = Path(args.cache_dir)

    manifest = cache.read_manifest(cache_dir)
    if manifest is None:
        raise SystemExit(
            f"{cache_dir}에 manifest.json이 없습니다. scripts/cache_fall_signals.py로 "
            "만든 캐시 디렉터리인지 확인하세요(holdout 가드를 다시 적용하려면 "
            "manifest의 split/videos_dir이 필요합니다)."
        )
    if args.split and args.split != manifest["split"]:
        raise SystemExit(
            f"--split={args.split!r}가 캐시 manifest의 split={manifest['split']!r}와 "
            "다릅니다 — 다른 split의 캐시를 잘못 지정했을 수 있습니다."
        )
    # 캐시를 한 번 만들면 이후에는 원본 영상 경로를 다시 거치지 않으므로,
    # holdout 가드도 manifest에 기록된 split/videos_dir로 매번 다시 확인한다
    # 캐시를 복사하거나 재사용해도 holdout 접근 정책이 유지되어야 한다.
    guard_holdout(Path(manifest["videos_dir"]), manifest["split"], rows, args.allow_holdout)

    print(f"[{args.split or cache_dir.name}] 캐시 {len(rows)}개 영상 재생 평가 시작")

    results: List[_VideoResult] = []
    for i, row in enumerate(rows, start=1):
        print(f"  ({i}/{len(rows)}) {row.video_id} [{row.label}] 재생 중...")
        result = _evaluate_row_from_cache(
            row,
            cache_dir,
            manifest,
            Path(manifest["videos_dir"]),
            config,
            args.config,
            args.early_tolerance_sec,
            args.timely_window_sec,
            args.fall_model_iou_threshold,
        )
        if result.error:
            print(f"    스킵: {result.error}")
        results.append(result)

    summary = _summarize(results)
    summary["split"] = args.split or cache_dir.name
    summary["run_config"] = {
        "source": "cache",
        "cache_dir": str(cache_dir),
        "config_path": args.config,
        "annotations_path": args.annotations,
        "early_tolerance_sec": args.early_tolerance_sec,
        "timely_window_sec": args.timely_window_sec,
        "fall_model_iou_threshold": args.fall_model_iou_threshold,
    }
    summary["excluded_from_evaluation"] = {"count": len(excluded_rows), "videos": excluded_rows}
    summary["videos"] = [video_result_to_dict(r) for r in results]

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as file:
        json.dump(summary, file, ensure_ascii=False, indent=2)

    print("\n=== 결과 요약(캐시 재생) ===")
    print(f"  평가 유효성(오류 영상 없음): {summary['evaluation_valid']}")
    print(f"  Recall: {summary['recall']} (목표 >= 0.75)")
    print(f"  timely_recall: {summary['timely_recall']} (목표 >= 0.75)")
    print(f"  False alarm/분: {summary['false_alarm_per_min']} (목표 <= 0.2)")
    print(f"  스킵된 영상: {summary['skipped_with_error']}")
    print(f"\n결과 저장: {output_path}")

    if not summary["evaluation_valid"]:
        raise SystemExit(
            f"{summary['skipped_with_error']}개 영상 처리 실패로 평가 결과를 신뢰할 수 "
            "없습니다. 결과 파일에서 error를 확인하세요(캐시가 없는 video_id는 먼저 "
            "scripts/cache_fall_signals.py로 생성해야 합니다)."
        )


if __name__ == "__main__":
    main()
