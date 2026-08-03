"""annotation CSV의 영상들을 한 번 추론해 Track/보조 모델 원본 detection을

`scripts/fall_signal_cache.py` 형식으로 캐싱한다.

FallDetector/FallPipeline은 전혀 실행하지 않는다 — 이 스크립트의 책임은
"YOLO pose + 보조 모델을 한 번 돌려서 원본 신호를 저장"까지이고, 상태머신
실행은 `scripts/evaluate_fall_from_cache.py`가 캐시를 읽어서 한다(추론과
평가를 분리해야 상태머신 실험마다 이 무거운 추론을 반복하지 않는다).

Usage:
    .venv/bin/python scripts/cache_fall_signals.py \
        --annotations data/annotations/caucafall_v5/development_annotations_v2.csv \
        --videos-dir data/datasets/caucafall/v5/development \
        --split development \
        --tracker pose --conf 0.5 \
        --fall-model-path outputs/fall_training/models/fall_detector_v1.pt \
        --cache-dir outputs/fall_eval/cache/pose_conf05_fallv1

주의: --split, --videos-dir, annotation의 각 video_path에 대해
evaluate_fall.py와 동일한 holdout 가드가 적용된다(Subject 9~10은 최종 평가
전까지 사용하지 않는다).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Optional

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import fall_signal_cache as cache  # noqa: E402
import fall_evaluation_protocol as evaluation_protocol  # noqa: E402
from evaluate_fall import (  # noqa: E402
    guard_holdout,
    load_annotations,
    resolve_video_path,
    validate_annotations,
)

from src.safety.auxiliary_fall_model import AuxiliaryFallModel  # noqa: E402
from src.tracking.bytetrack_wrapper import ByteTracker  # noqa: E402
from src.tracking.pose_tracker import PoseTracker  # noqa: E402


def _resolved_device_or_exit(component_name: str, provider, requested_device: str) -> str:
    """장시간 캐싱 전에 실제 inference device provenance를 fail-fast 검증한다."""
    resolved_device = getattr(provider, "_device", requested_device)
    try:
        return evaluation_protocol.normalize_resolved_device(
            resolved_device, component_name
        )
    except ValueError as exc:
        raise SystemExit(
            f"{exc}. cache 생성을 시작하지 않습니다. "
            "명시적 --device/--fall-model-device를 사용하거나 wrapper가 "
            "실제 device를 노출하도록 수정하세요."
        ) from exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--annotations", required=True, help="annotation CSV 경로")
    parser.add_argument("--videos-dir", required=True, help="video_path의 기준 디렉터리")
    parser.add_argument("--split", default="", help="development | validation | holdout")
    parser.add_argument(
        "--tracker", default="pose", choices=["bbox", "pose"], help="evaluate_fall.py와 동일"
    )
    parser.add_argument("--model", default=None)
    parser.add_argument("--conf", type=float, default=0.5)
    parser.add_argument("--device", default="auto")
    parser.add_argument("--fall-model-path", default=None)
    parser.add_argument("--fall-model-conf", type=float, default=0.5)
    parser.add_argument("--fall-model-device", default="auto")
    parser.add_argument("--cache-dir", required=True, help="캐시 파일을 쓸 디렉터리")
    parser.add_argument("--include-unreviewed", action="store_true")
    parser.add_argument("--allow-holdout", action="store_true")
    parser.add_argument(
        "--force", action="store_true", help="이미 캐시된 video_id도 다시 추론해 덮어쓴다."
    )
    return parser.parse_args()


def _cache_one_video(
    video_id: str,
    video_path: Path,
    tracker,
    auxiliary_model,
    cache_dir: Path,
    tracker_meta: dict,
    auxiliary_meta: Optional[dict],
) -> dict:
    """영상 하나를 캐싱하고 {"frame_count", "elapsed_sec"}을 반환한다.

    elapsed_sec은 디코딩+tracker+보조 모델 추론 루프만 잰다(캐시 JSON
    직렬화·디스크 쓰기는 제외). Tracker Sweep에서 conf별 처리 FPS를 비교할
    때 파이프라인 자체의 속도만 있어야 하고, 캐시 저장
    비용이 섞이면 실제 운영 FPS와 무관한 잡음이 낀다.
    """
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"영상을 열 수 없습니다: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    tracker.fps = fps
    tracker.reset()

    frames = []
    frame_number = 0
    start = time.perf_counter()
    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            result = tracker.update(frame, frame_number, video_id)
            raw_detections = None
            if auxiliary_model is not None and auxiliary_model.enabled:
                # Track이 없으면 매칭할 대상도 없다 — 빈 리스트로 "모델은 켜져
                # 있었지만 이번 프레임엔 대상이 없었다"를 표현한다. None(모델
                # 완전 비활성화)과는 다른 의미다 (fall_signal_cache.py 참고).
                raw_detections = auxiliary_model.infer(frame) if result.tracks else []
            frames.append(
                cache.CachedFrame(
                    frame_number=frame_number,
                    timestamp=result.timestamp,
                    tracks=result.tracks,
                    raw_detections=raw_detections,
                )
            )
            frame_number += 1
    finally:
        cap.release()
    elapsed_sec = time.perf_counter() - start

    cache.write_video_cache(
        cache.cache_path_for(cache_dir, video_id),
        video_id=video_id,
        fps=fps,
        tracker_meta=tracker_meta,
        auxiliary_meta=auxiliary_meta,
        frames=frames,
        video_path=str(video_path.resolve()),
        video_size_bytes=video_path.stat().st_size,
    )
    return {"frame_count": frame_number, "elapsed_sec": elapsed_sec}


def main() -> None:
    args = parse_args()
    videos_dir = Path(args.videos_dir)
    cache_dir = Path(args.cache_dir)

    try:
        rows = load_annotations(args.annotations, include_unreviewed=args.include_unreviewed)
        if not rows:
            raise ValueError("캐싱할 annotation 행이 없습니다 (review_status='reviewed' 확인).")
        validate_annotations(rows)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    guard_holdout(videos_dir, args.split, rows, args.allow_holdout)

    tracker_cls = PoseTracker if args.tracker == "pose" else ByteTracker
    default_model = "yolo26n-pose.pt" if args.tracker == "pose" else "yolo26n.pt"
    model_path = args.model or default_model
    tracker = tracker_cls(model_path=model_path, conf=args.conf, fps=30.0, device=args.device)
    tracker_resolved_device = _resolved_device_or_exit(
        "tracker", tracker, args.device
    )
    tracker_meta = {
        "tracker_type": args.tracker,
        "model_path": model_path,
        "model_sha256": cache.sha256_file(model_path),
        "conf": args.conf,
        "tracker_config": "bytetrack.yaml",
        "tracker_config_sha256": cache.sha256_file("bytetrack.yaml"),
        "requested_device": args.device,
        "resolved_device": tracker_resolved_device,
    }

    auxiliary_model = None
    auxiliary_meta = None
    if args.fall_model_path is not None:
        auxiliary_model = AuxiliaryFallModel(
            model_path=args.fall_model_path,
            conf=args.fall_model_conf,
            device=args.fall_model_device,
            enabled=True,
        )
        auxiliary_resolved_device = _resolved_device_or_exit(
            "auxiliary model", auxiliary_model, args.fall_model_device
        )
        auxiliary_meta = {
            "model_path": args.fall_model_path,
            "model_sha256": cache.sha256_file(args.fall_model_path),
            "conf": args.fall_model_conf,
            "requested_device": args.fall_model_device,
            "resolved_device": auxiliary_resolved_device,
        }

    manifest = cache.build_manifest(
        split=args.split,
        videos_dir=str(videos_dir.resolve()),
        tracker_meta=tracker_meta,
        auxiliary_meta=auxiliary_meta,
    )
    existing_manifest = cache.read_manifest(cache_dir)
    manifest_changed = existing_manifest is not None and existing_manifest != manifest
    if manifest_changed and not args.force:
        raise SystemExit(
            f"{cache_dir}의 기존 manifest와 이번 실행 설정이 다릅니다 — Pose/bbox tracker, "
            "conf, 모델 파일, 보조 모델 사용 여부가 섞인 캐시 디렉터리가 만들어질 수 "
            "있어 그냥 진행하지 않습니다.\n"
            f"기존: {json.dumps(existing_manifest, ensure_ascii=False, indent=2)}\n"
            f"이번: {json.dumps(manifest, ensure_ascii=False, indent=2)}\n"
            "설정이 의도한 변경이면 --force로 이 디렉터리 전체를 재생성하거나, "
            "다른 --cache-dir을 쓰세요."
        )
    if manifest_changed:
        print(f"경고: {cache_dir}의 manifest가 이전과 달라 --force로 전체 재생성합니다.")
    # manifest가 없는데 개별 영상 캐시(*.json)는 이미 있는 디렉터리는 신뢰할
    # 수 없다 — manifest 도입 이전에 만들어졌거나, 이전 실행이 manifest를
    # 쓰기 전에(전체 성공 전에) 중단됐을 수 있다.
    if existing_manifest is None and cache.has_existing_video_caches(cache_dir) and not args.force:
        raise SystemExit(
            f"{cache_dir}에 manifest.json 없이 캐시 파일이 이미 있습니다 — 이전 실행이 "
            "manifest 도입 전이었거나 끝까지 완료되지 못했을 수 있습니다. --force로 "
            "전체 재생성하거나 새 --cache-dir을 쓰세요."
        )
    # manifest가 이번에 새로 생겼거나 바뀌었으면, 그 디렉터리에 남아 있는 개별
    # 영상 캐시는 이제 신뢰할 수 없는 설정으로 만들어졌을 수 있다 — --force
    # 여부와 무관하게 이번 실행에서는 전부 다시 만든다.
    force_all = args.force or manifest_changed

    cache_dir.mkdir(parents=True, exist_ok=True)
    if force_all:
        # 중간 실패 후 일부만 갱신된 캐시를 완전한 결과로 오인하지 않도록
        # 전체 재생성을 시작하기 전에 기존 manifest를 무효화한다.
        cache.manifest_path_for(cache_dir).unlink(missing_ok=True)
    cached_count = 0
    skipped_count = 0
    per_video_fps: dict = {}
    total_frames = 0
    total_elapsed_sec = 0.0
    for i, row in enumerate(rows, start=1):
        output_path = cache.cache_path_for(cache_dir, row.video_id)
        if output_path.exists() and not force_all:
            print(f"  ({i}/{len(rows)}) {row.video_id}: 이미 캐시됨, 건너뜀 (--force로 재생성)")
            skipped_count += 1
            continue

        video_path = resolve_video_path(row, videos_dir)
        print(f"  ({i}/{len(rows)}) {row.video_id} 캐싱 중...")
        timing = _cache_one_video(
            row.video_id,
            video_path,
            tracker,
            auxiliary_model,
            cache_dir,
            tracker_meta,
            auxiliary_meta,
        )
        if timing["elapsed_sec"] > 0:
            per_video_fps[row.video_id] = timing["frame_count"] / timing["elapsed_sec"]
        total_frames += timing["frame_count"]
        total_elapsed_sec += timing["elapsed_sec"]
        cached_count += 1

    # manifest는 전체 영상이 성공적으로 캐싱된 뒤에야 쓴다 — 루프 중간에
    # 중단되면(에러/Ctrl+C) manifest가 아예 없는 상태로 남아, 다음 실행이
    # "manifest 없이 캐시 파일만 있음" 가드에 걸려 안전하게 --force를
    # 요구하게 된다. 미리 쓰면 중단 후 재실행 시 옛 캐시가 새 manifest
    # 아래 조용히 섞여 남을 수 있다.
    cache.write_manifest(cache_dir, manifest)

    # 이번 실행에서 새로 캐싱한 영상만 집계한다 — 건너뛴 영상은 이번
    # 하드웨어·실행에서 다시 측정된 게 아니라 timing 값이 없다. Tracker
    # Sweep이 conf별 처리 FPS를 비교하는 데 쓴다.
    if cached_count > 0 and total_elapsed_sec > 0:
        timing_report = {
            "videos_timed": cached_count,
            "skipped_count": skipped_count,
            "total_frames": total_frames,
            "total_elapsed_sec": total_elapsed_sec,
            "fps_avg": total_frames / total_elapsed_sec,
            "per_video_fps": per_video_fps,
        }
        with open(cache_dir / "timing_report.json", "w", encoding="utf-8") as file:
            json.dump(timing_report, file, ensure_ascii=False, indent=2)
        print(
            f"처리 FPS(이번 실행 신규 캐싱분 평균, cold-start 포함): "
            f"{timing_report['fps_avg']:.2f}"
        )

    print(f"\n캐싱 완료: {cached_count}개 새로 생성, {skipped_count}개 건너뜀 -> {cache_dir}")


if __name__ == "__main__":
    main()
