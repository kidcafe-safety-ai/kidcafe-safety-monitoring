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
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import fall_signal_cache as cache  # noqa: E402
from scripts import fall_evaluation_protocol as evaluation_protocol  # noqa: E402
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
from src.safety.auxiliary_fall_model import FallDetection  # noqa: E402
from src.safety.fall_detector import FallDetectorConfig  # noqa: E402
from src.safety.fall_pipeline import (  # noqa: E402
    AdaptiveAuxiliaryInferenceCadence,
    validate_auxiliary_inference_interval_frames,
)
from src.safety.fall_model_matching import match_detections_to_tracks  # noqa: E402
from src.safety.pose_normal_gate import PoseNormalGate, PoseNormalGateConfig  # noqa: E402


@dataclass
class PoseGateStats:
    track_present_frames: int = 0
    safe_normal_frames: int = 0
    fallback_frames: int = 0
    fallback_unready_frames: int = 0
    fallback_pose_unavailable_frames: int = 0
    fallback_descending_frames: int = 0
    fallback_non_normal_frames: int = 0
    auxiliary_inference_frames: int = 0
    gate_evaluation_frames: int = 0
    gate_elapsed_sec: float = 0.0

    def add(self, other: "PoseGateStats") -> None:
        for name in self.__dataclass_fields__:
            setattr(self, name, getattr(self, name) + getattr(other, name))

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["fallback_frame_ratio"] = (
            self.fallback_frames / self.track_present_frames
            if self.track_present_frames
            else None
        )
        payload["auxiliary_inference_frame_ratio"] = (
            self.auxiliary_inference_frames / self.track_present_frames
            if self.track_present_frames
            else None
        )
        payload["avg_gate_evaluation_sec"] = (
            self.gate_elapsed_sec / self.gate_evaluation_frames
            if self.gate_evaluation_frames
            else None
        )
        return payload


class CachedAdaptiveAuxiliaryCadence:
    """Apply the runtime fallback schedule to cached raw detections."""

    def __init__(self, interval_frames: int, iou_threshold: float):
        self._schedule = AdaptiveAuxiliaryInferenceCadence(interval_frames)
        self.iou_threshold = iou_threshold
        self._last_evidence = {}

    def reset(self) -> None:
        self._schedule.reset()
        self._last_evidence = {}

    def resolve(
        self,
        tracking_result: TrackingResult,
        selected_detections: List[FallDetection],
        raw_detections: Optional[List[FallDetection]],
        use_auxiliary: bool,
    ) -> tuple[List[FallDetection], bool]:
        if not tracking_result.tracks or not use_auxiliary:
            self.reset()
            return selected_detections, False
        if raw_detections is None:
            raise ValueError("pose normal gate requires cached auxiliary detections")

        if self._schedule.should_infer(tracking_result, use_auxiliary=True):
            evidence = match_detections_to_tracks(
                tracking_result.tracks,
                raw_detections,
                self.iou_threshold,
            )
            self._last_evidence = {item.track_id: item for item in evidence}
            return raw_detections, True

        held_detections = []
        for track in tracking_result.tracks:
            evidence = self._last_evidence.get(track.track_id)
            if evidence is None or evidence.label == "unknown":
                continue
            held_detections.append(
                FallDetection(
                    bbox=list(track.bbox),
                    label=evidence.label,
                    confidence=float(evidence.confidence),
                )
            )
        return held_detections, False


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
    parser.add_argument(
        "--fall-model-interval-frames",
        type=int,
        default=1,
        help="캐시된 보조 모델 detection을 사용할 고정 frame 간격.",
    )
    parser.add_argument(
        "--fall-pose-normal-gate-enabled",
        action="store_true",
        help="안정적인 직립 Pose에서는 보조 모델 detection을 사용하지 않는다.",
    )
    parser.add_argument("--output", default="outputs/fall_eval/from_cache_summary.json")
    parser.add_argument("--include-unreviewed", action="store_true")
    parser.add_argument(
        "--allow-holdout",
        action="store_true",
        help="캐시 manifest의 split/videos_dir이 holdout이어도 명시적으로 허용한다.",
    )
    evaluation_protocol.add_cli_argument(parser)
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


def _normal_detections(tracking_result: TrackingResult) -> List[FallDetection]:
    return [
        FallDetection(
            bbox=list(track.bbox),
            label="nofall",
            confidence=track.confidence,
        )
        for track in tracking_result.tracks
    ]


def _frame_source_from_pose_gate(
    cached_frames,
    video_id: str,
    fps: float,
    interval_frames: int,
    iou_threshold: float,
    gate_config: PoseNormalGateConfig,
    stats: PoseGateStats,
):
    gate = PoseNormalGate(fps=fps, config=gate_config)
    cadence = CachedAdaptiveAuxiliaryCadence(interval_frames, iou_threshold)
    for cached_frame in cached_frames:
        tracking_result = TrackingResult(
            frame_number=cached_frame.frame_number,
            timestamp=cached_frame.timestamp,
            video_source=video_id,
            tracks=cached_frame.tracks,
        )
        started = time.perf_counter()
        decision = gate.evaluate(tracking_result)
        stats.gate_elapsed_sec += time.perf_counter() - started
        stats.gate_evaluation_frames += 1
        if tracking_result.tracks:
            stats.track_present_frames += 1
            stats.safe_normal_frames += int(not decision.use_auxiliary)
        stats.fallback_frames += int(decision.use_auxiliary)
        stats.fallback_unready_frames += int(decision.unready)
        stats.fallback_pose_unavailable_frames += int(decision.pose_unavailable)
        stats.fallback_descending_frames += int(decision.descending)
        stats.fallback_non_normal_frames += int(decision.non_normal_posture)

        selected = (
            cached_frame.raw_detections
            if decision.use_auxiliary
            else _normal_detections(tracking_result)
        )
        if selected is None:
            raise ValueError("pose normal gate requires cached auxiliary detections")
        detections, inferred = cadence.resolve(
            tracking_result,
            selected,
            cached_frame.raw_detections,
            decision.use_auxiliary,
        )
        stats.auxiliary_inference_frames += int(inferred)
        yield cached_frame.frame_number, tracking_result, detections


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
    fall_model_interval_frames: int,
    pose_normal_gate_enabled: bool = False,
    pose_gate_stats: Optional[PoseGateStats] = None,
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
    if pose_normal_gate_enabled:
        if pose_gate_stats is None:
            raise ValueError("pose_gate_stats is required when pose normal gate is enabled")
        frame_source = _frame_source_from_pose_gate(
            frames,
            row.video_id,
            fps,
            fall_model_interval_frames,
            fall_model_iou_threshold,
            PoseNormalGateConfig.from_fall_detector_config(config),
            pose_gate_stats,
        )
        scorer_interval_frames = 1
    else:
        frame_source = _frame_source_from_cache(frames, row.video_id)
        scorer_interval_frames = fall_model_interval_frames
    return score_video_from_frame_source(
        row,
        frame_source,
        fps,
        config,
        fall_config_path=fall_config_path,
        fall_model_iou_threshold=fall_model_iou_threshold,
        fall_model_interval_frames=scorer_interval_frames,
        early_tolerance_sec=early_tolerance_sec,
        timely_window_sec=timely_window_sec,
    )


def _build_cache_protocol_metadata(
    args, annotation_schema_version: str, manifest: dict
) -> dict:
    tracker_meta = manifest["tracker"]
    auxiliary_meta = manifest["auxiliary_model"]
    return evaluation_protocol.build_metadata(
        annotation_schema_version=annotation_schema_version,
        model_sha256=auxiliary_meta["model_sha256"],
        config_path=args.config,
        tracker=tracker_meta["tracker_type"],
        tracker_config=tracker_meta,
        device={
            "tracker": tracker_meta["resolved_device"],
            "auxiliary_model": auxiliary_meta["resolved_device"],
            "evaluation": "cache_replay",
        },
    )


def main() -> None:
    args = parse_args()

    if args.timely_window_sec <= 0:
        raise SystemExit(f"--timely-window-sec는 0보다 커야 합니다: {args.timely_window_sec}")
    if args.early_tolerance_sec < 0:
        raise SystemExit(f"--early-tolerance-sec는 0 이상이어야 합니다: {args.early_tolerance_sec}")
    try:
        validate_auxiliary_inference_interval_frames(args.fall_model_interval_frames)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    try:
        annotation_schema_version = evaluation_protocol.validate_protocol_request(
            args.evaluation_protocol_version,
            args.annotations,
            args.early_tolerance_sec,
            args.timely_window_sec,
            args.include_unreviewed,
        )
    except (OSError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc

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
    if annotation_schema_version is not None:
        try:
            evaluation_protocol.validate_official_cache_manifest(manifest)
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
    if args.split and args.split != manifest["split"]:
        raise SystemExit(
            f"--split={args.split!r}가 캐시 manifest의 split={manifest['split']!r}와 "
            "다릅니다 — 다른 split의 캐시를 잘못 지정했을 수 있습니다."
        )
    # 캐시를 한 번 만들면 이후에는 원본 영상 경로를 다시 거치지 않으므로,
    # holdout 가드도 manifest에 기록된 split/videos_dir로 매번 다시 확인한다
    # 캐시를 복사하거나 재사용해도 holdout 접근 정책이 유지되어야 한다.
    guard_holdout(Path(manifest["videos_dir"]), manifest["split"], rows, args.allow_holdout)

    protocol_metadata = {}
    if annotation_schema_version is not None:
        try:
            protocol_metadata = _build_cache_protocol_metadata(
                args, annotation_schema_version, manifest
            )
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc

    print(f"[{args.split or cache_dir.name}] 캐시 {len(rows)}개 영상 재생 평가 시작")

    results: List[_VideoResult] = []
    aggregate_pose_gate_stats = PoseGateStats()
    pose_gate_stats_by_video = {}
    for i, row in enumerate(rows, start=1):
        print(f"  ({i}/{len(rows)}) {row.video_id} [{row.label}] 재생 중...")
        video_pose_gate_stats = PoseGateStats()
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
            args.fall_model_interval_frames,
            pose_normal_gate_enabled=args.fall_pose_normal_gate_enabled,
            pose_gate_stats=video_pose_gate_stats,
        )
        if result.error:
            print(f"    스킵: {result.error}")
        results.append(result)
        if args.fall_pose_normal_gate_enabled:
            aggregate_pose_gate_stats.add(video_pose_gate_stats)
            pose_gate_stats_by_video[row.video_id] = video_pose_gate_stats.to_dict()

    summary = _summarize(results)
    summary.update(protocol_metadata)
    summary["split"] = args.split or cache_dir.name
    summary["run_config"] = {
        "source": "cache",
        "cache_dir": str(cache_dir),
        "config_path": args.config,
        "annotations_path": args.annotations,
        "early_tolerance_sec": args.early_tolerance_sec,
        "timely_window_sec": args.timely_window_sec,
        "fall_model_iou_threshold": args.fall_model_iou_threshold,
        "fall_model_interval_frames": args.fall_model_interval_frames,
        "fall_pose_normal_gate_enabled": args.fall_pose_normal_gate_enabled,
        "pose_normal_gate_config": (
            asdict(PoseNormalGateConfig.from_fall_detector_config(config))
            if args.fall_pose_normal_gate_enabled
            else None
        ),
    }
    if args.fall_pose_normal_gate_enabled:
        summary["pose_normal_gate"] = aggregate_pose_gate_stats.to_dict()
        summary["pose_normal_gate_by_video"] = pose_gate_stats_by_video
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
