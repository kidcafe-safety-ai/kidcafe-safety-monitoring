"""12개 다중 인원 영상을 E1 selected profile로 캐시 재생해 Event를 그대로 뽑는다.

`scripts/evaluate_fall.py`의 `score_video_from_frame_source()`와 동일하게
`FallPipeline`을 구성해 재생하지만, 그 함수처럼 Event를 frame_number로
축약하지 않고 `track_id`(victim)·`cause`(predicted cause track/score)까지
그대로 보존한다. YOLO·Pose 재추론은 하지 않는다 — 캐시된 bbox·Pose·
raw_detections만 재생한다.

무결성 검증(fail-closed): tracker·auxiliary model·추론 설정이
`configs/fall_e1_selected.json`의 동결값과 같아야 한다.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import List

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import fall_signal_cache as cache  # noqa: E402
import phase4_recording_contract as contract  # noqa: E402
import phase4_tracker_comparison_contract as comparison_contract  # noqa: E402
from evaluate_fall_from_cache import (  # noqa: E402
    PoseGateStats,
    _frame_source_from_cache,
    _frame_source_from_pose_gate,
)
from generate_phase4_track_actor_segments import (  # noqa: E402
    DEFAULT_CACHE_SOURCE_ANNOTATIONS,
    DEFAULT_CACHE_SOURCE_MANIFEST,
    DEFAULT_SCENARIOS,
    select_target_video_ids,
    verify_cache_integrity,
)

from src.common.types import Event  # noqa: E402
from src.safety.fall_detector import FallDetectorConfig  # noqa: E402
from src.safety.fall_pipeline import AuxiliaryEvidenceCadence, FallPipeline  # noqa: E402
from src.safety.fall_model_matching import match_detections_to_tracks  # noqa: E402
from src.safety.pose_normal_gate import PoseNormalGateConfig  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--annotations", required=True)
    parser.add_argument("--cache-dir", required=True)
    parser.add_argument("--selected-profile", default="configs/fall_e1_selected.json")
    parser.add_argument(
        "--tracker-comparison-config",
        default=None,
        help="Tracker 비교 실행이면 phase4_tracker_comparison_v1 JSON 경로",
    )
    parser.add_argument(
        "--tracker-arm-id",
        choices=comparison_contract.ARM_IDS,
        default=None,
        help="--tracker-comparison-config와 함께 지정한다.",
    )
    parser.add_argument(
        "--cache-source-manifest", default=DEFAULT_CACHE_SOURCE_MANIFEST
    )
    parser.add_argument(
        "--cache-source-annotations", default=DEFAULT_CACHE_SOURCE_ANNOTATIONS
    )
    parser.add_argument(
        "--scenario", action="append", default=None, help=f"기본값: {','.join(DEFAULT_SCENARIOS)}"
    )
    parser.add_argument("--video-id", action="append", default=None)
    parser.add_argument(
        "--config",
        default="configs/fall_detection.json",
        help="selected profile의 inference.fall_detector_config_path와 같아야 한다.",
    )
    parser.add_argument(
        "--fall-model-iou-threshold",
        type=float,
        default=0.3,
        help="selected profile의 값과 같아야 한다.",
    )
    parser.add_argument(
        "--fall-model-interval-frames",
        type=int,
        default=3,
        help="selected profile의 값과 같아야 한다.",
    )
    parser.add_argument(
        "--fall-pose-normal-gate-enabled",
        type=lambda v: v.lower() == "true",
        default=True,
        help="selected profile의 값과 같아야 한다 (true/false).",
    )
    parser.add_argument("--output", required=True)
    return parser.parse_args()


def _verify_settings_match_selected_profile(
    selected: dict, args: argparse.Namespace
) -> None:
    inference = selected["inference"]
    errors: List[str] = []
    if inference["fall_detector_config_path"] != args.config:
        errors.append(
            f"--config={args.config!r} != selected profile "
            f"fall_detector_config_path={inference['fall_detector_config_path']!r}"
        )
    actual_config_sha = contract.sha256_file(args.config)
    expected_config_sha = inference["fall_detector_config_sha256"]
    if actual_config_sha != expected_config_sha:
        errors.append(
            f"--config SHA-256={actual_config_sha} != selected {expected_config_sha}"
        )
    if inference["fall_model_iou_threshold"] != args.fall_model_iou_threshold:
        errors.append(
            f"--fall-model-iou-threshold={args.fall_model_iou_threshold} != "
            f"selected {inference['fall_model_iou_threshold']}"
        )
    if inference["fall_model_interval_frames"] != args.fall_model_interval_frames:
        errors.append(
            f"--fall-model-interval-frames={args.fall_model_interval_frames} != "
            f"selected {inference['fall_model_interval_frames']}"
        )
    if inference["fall_pose_normal_gate_enabled"] != args.fall_pose_normal_gate_enabled:
        errors.append(
            f"--fall-pose-normal-gate-enabled={args.fall_pose_normal_gate_enabled} != "
            f"selected {inference['fall_pose_normal_gate_enabled']}"
        )
    if errors:
        raise ValueError("selected profile 설정 불일치:\n  - " + "\n  - ".join(errors))


def verify_replay_inputs(
    *,
    args: argparse.Namespace,
    selected: dict,
    manifest_rows: List[dict],
    annotation_rows: List[dict],
    video_ids: List[str],
) -> None:
    """Selected profile과 cache·dataset revision을 입력 열기 전에 검증한다."""
    _verify_settings_match_selected_profile(selected, args)
    verify_cache_integrity(
        cache_dir=Path(args.cache_dir),
        manifest_path=Path(args.manifest),
        annotations_path=Path(args.annotations),
        selected_profile_path=Path(args.selected_profile),
        cache_source_manifest_path=Path(args.cache_source_manifest),
        cache_source_annotations_path=Path(args.cache_source_annotations),
        manifest_by_video={row["video_id"]: row for row in manifest_rows},
        annotation_by_video={row["video_id"]: row for row in annotation_rows},
        video_ids=video_ids,
    )


def _event_to_dict(event: Event) -> dict:
    payload = {
        "frame_number": event.frame_number,
        "timestamp": event.timestamp,
        "track_id": event.track_id,
        "confidence": event.confidence,
        "event_confidence": event.event_confidence,
        "cause": None,
    }
    if event.cause is not None:
        payload["cause"] = {
            "type": event.cause.type,
            "track_id": event.cause.track_id,
            "score": event.cause.score,
            "evidence": asdict(event.cause.evidence),
        }
    return payload


def replay_video(
    *,
    video_id: str,
    cache_dir: Path,
    cache_manifest: dict,
    config: FallDetectorConfig,
    fall_config_path: str,
    fall_model_iou_threshold: float,
    fall_model_interval_frames: int,
    pose_normal_gate_enabled: bool,
) -> dict:
    cache_file = cache.cache_path_for(cache_dir, video_id)
    metadata, frames = cache.read_video_cache(cache_file, expected_video_id=video_id)
    if metadata["tracker"] != cache_manifest["tracker"]:
        raise ValueError(f"{video_id}: cache tracker 설정이 디렉터리 manifest와 다릅니다.")
    if metadata["auxiliary_model"] != cache_manifest["auxiliary_model"]:
        raise ValueError(f"{video_id}: cache auxiliary_model 설정이 디렉터리 manifest와 다릅니다.")

    fps = metadata["fps"]
    pose_gate_stats = PoseGateStats()
    if pose_normal_gate_enabled:
        frame_source = _frame_source_from_pose_gate(
            frames,
            video_id,
            fps,
            fall_model_interval_frames,
            fall_model_iou_threshold,
            PoseNormalGateConfig.from_fall_detector_config(config),
            pose_gate_stats,
        )
        scorer_interval_frames = 1
    else:
        frame_source = _frame_source_from_cache(frames, video_id)
        scorer_interval_frames = fall_model_interval_frames

    pipeline = FallPipeline(fps=fps, detector_config=config, fall_config_path=fall_config_path)
    evidence_cadence = AuxiliaryEvidenceCadence(scorer_interval_frames)

    events: List[Event] = []
    frame_count = 0
    for frame_number, tracking_result, raw_detections in frame_source:
        frame_count += 1
        model_evidence = None
        if raw_detections is not None:
            fresh_evidence = None
            if evidence_cadence.should_infer(frame_number):
                evidence_list = match_detections_to_tracks(
                    tracking_result.tracks, raw_detections, fall_model_iou_threshold
                )
                fresh_evidence = {evidence.track_id: evidence for evidence in evidence_list}
            model_evidence = evidence_cadence.resolve(tracking_result, fresh_evidence)
        events.extend(pipeline.process_with_evidence(tracking_result, model_evidence))

    return {
        "video_id": video_id,
        "frame_count": frame_count,
        "fps": fps,
        "event_count": len(events),
        "events": [_event_to_dict(event) for event in events],
    }


def main() -> None:
    args = parse_args()
    try:
        if bool(args.tracker_comparison_config) != bool(args.tracker_arm_id):
            raise ValueError(
                "--tracker-comparison-config와 --tracker-arm-id는 함께 지정해야 합니다."
            )
        selected = json.loads(Path(args.selected_profile).read_text(encoding="utf-8"))
        config = FallDetectorConfig.from_file(args.config)

        manifest_rows = contract.load_recordings_manifest(args.manifest)
        annotation_rows = contract.load_fall_cause_annotations(
            args.annotations, manifest_rows
        )
        video_ids = select_target_video_ids(
            manifest_rows,
            scenarios=args.scenario or DEFAULT_SCENARIOS,
            explicit_video_ids=args.video_id,
        )
        if not video_ids:
            raise ValueError("대상 video_id가 없습니다.")

        cache_dir = Path(args.cache_dir)
        verify_replay_inputs(
            args=args,
            selected=selected,
            manifest_rows=manifest_rows,
            annotation_rows=annotation_rows,
            video_ids=video_ids,
        )
        cache_manifest = cache.read_manifest(cache_dir)
        if cache_manifest is None:
            raise ValueError(f"{cache_dir}에 manifest.json이 없습니다.")
        comparison_arm = None
        if args.tracker_comparison_config:
            comparison = comparison_contract.load_config(
                args.tracker_comparison_config,
                require_model_artifacts=False,
            )
            comparison_contract.validate_cohort(
                comparison, manifest_rows, annotation_rows
            )
            comparison_arm = comparison_contract.arm_by_id(
                comparison, args.tracker_arm_id
            )
            comparison_contract.validate_cache_arm(cache_manifest, comparison_arm)

        results = []
        for video_id in video_ids:
            print(f"재생 중: {video_id}")
            results.append(
                replay_video(
                    video_id=video_id,
                    cache_dir=cache_dir,
                    cache_manifest=cache_manifest,
                    config=config,
                    fall_config_path=args.config,
                    fall_model_iou_threshold=args.fall_model_iou_threshold,
                    fall_model_interval_frames=args.fall_model_interval_frames,
                    pose_normal_gate_enabled=args.fall_pose_normal_gate_enabled,
                )
            )

        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8") as file:
            payload = {
                    "selected_execution_profile_sha256": (
                        contract.selected_execution_profile_sha256(selected)
                    ),
                    "cache_manifest_sha256": contract.sha256_file(
                        cache_dir / "manifest.json"
                    ),
                    "recordings_manifest_sha256": contract.sha256_file(args.manifest),
                    "fall_cause_annotations_sha256": contract.sha256_file(
                        args.annotations
                    ),
                    "config_path": args.config,
                    "config_sha256": contract.sha256_file(args.config),
                    "fall_model_iou_threshold": args.fall_model_iou_threshold,
                    "fall_model_interval_frames": args.fall_model_interval_frames,
                    "fall_pose_normal_gate_enabled": args.fall_pose_normal_gate_enabled,
                    "videos": results,
                }
            if comparison_arm is not None:
                payload["tracker_comparison_arm"] = (
                    comparison_contract.arm_provenance(comparison_arm)
                )
            json.dump(
                payload,
                file,
                ensure_ascii=False,
                indent=2,
            )
    except (OSError, ValueError, KeyError) as exc:
        raise SystemExit(str(exc)) from exc

    total_events = sum(r["event_count"] for r in results)
    print(f"\n{len(results)}개 영상, 총 {total_events}개 Event -> {output_path}")
    for r in results:
        causes = sum(1 for e in r["events"] if e["cause"] is not None)
        print(f"  {r['video_id']}: {r['event_count']} events ({causes}개 cause 있음)")


if __name__ == "__main__":
    main()
