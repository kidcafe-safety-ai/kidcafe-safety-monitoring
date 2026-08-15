"""Phase 4 직접 촬영 E0의 미탐 원인을 Signal Cache에서 진단한다.

공식 Recall/FAR는 ``evaluate_fall_from_cache.py``가 계산한다. 이 도구는 같은
결과와 Cache를 결합해 timely window 안에서 candidate 진입 근거, bbox/Pose
확정 근거, 보조 모델 근거가 실제 임계값에 도달했는지 요약한다. 자동으로
임계값을 채택하거나 test split을 열지 않는 진단 전용 도구다.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import fall_signal_cache as signal_cache  # noqa: E402
from src.common.types import TrackingResult  # noqa: E402
from src.safety.fall_detector import FallDetectorConfig  # noqa: E402
from src.safety.fall_features import FallFeatureExtractor  # noqa: E402
from src.safety.fall_model_matching import match_detections_to_tracks  # noqa: E402
from src.safety.multi_track_history import MultiTrackHistory  # noqa: E402
from src.safety.pose_features import PoseFeatureExtractor  # noqa: E402


SCHEMA_VERSION = "phase4_recorded_e0_diagnostics_v1"


class RecordedE0AnalysisError(ValueError):
    """입력 결과·annotation·Cache가 진단 계약을 만족하지 않을 때 발생한다."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evaluation", required=True, help="E0 cache replay 결과 JSON")
    parser.add_argument("--annotations", required=True)
    parser.add_argument("--cache-dir", required=True)
    parser.add_argument("--config", default="configs/fall_detection.json")
    parser.add_argument("--output", required=True)
    return parser.parse_args()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path, description: str) -> dict:
    if not path.is_file():
        raise RecordedE0AnalysisError(f"{description} 파일이 없습니다: {path}")
    try:
        with open(path, "r", encoding="utf-8") as file:
            payload = json.load(file)
    except (OSError, json.JSONDecodeError) as exc:
        raise RecordedE0AnalysisError(f"{description} JSON을 읽을 수 없습니다: {exc}") from exc
    if not isinstance(payload, dict):
        raise RecordedE0AnalysisError(f"{description} JSON root는 객체여야 합니다.")
    return payload


def load_evaluation(path: Path) -> tuple[dict, dict[str, dict]]:
    payload = _load_json(path, "evaluation")
    if payload.get("evaluation_valid") is not True:
        raise RecordedE0AnalysisError("evaluation_valid=true인 결과만 분석할 수 있습니다.")
    if payload.get("split") != "diagnostic":
        raise RecordedE0AnalysisError("직접 촬영 diagnostic split 결과만 분석할 수 있습니다.")
    videos = payload.get("videos")
    if not isinstance(videos, list) or not videos:
        raise RecordedE0AnalysisError("evaluation videos가 비어 있습니다.")

    by_id = {}
    for video in videos:
        video_id = video.get("video_id") if isinstance(video, dict) else None
        if not isinstance(video_id, str) or not video_id or video_id in by_id:
            raise RecordedE0AnalysisError(f"video_id가 비었거나 중복됩니다: {video_id!r}")
        if video.get("error") is not None:
            raise RecordedE0AnalysisError(f"오류 영상이 포함돼 있습니다: {video_id}")
        by_id[video_id] = video
    return payload, by_id


def load_annotations(path: Path) -> dict[str, dict]:
    if not path.is_file():
        raise RecordedE0AnalysisError(f"annotation 파일이 없습니다: {path}")
    with open(path, "r", encoding="utf-8", newline="") as file:
        rows = list(csv.DictReader(file))
    by_id = {}
    for row in rows:
        video_id = (row.get("video_id") or "").strip()
        if not video_id or video_id in by_id:
            raise RecordedE0AnalysisError(f"annotation video_id가 비었거나 중복됩니다: {video_id!r}")
        by_id[video_id] = row
    return by_id


def _optional_int(value: object, field: str, video_id: str) -> Optional[int]:
    text = "" if value is None else str(value).strip()
    if not text:
        return None
    try:
        parsed = int(text)
    except ValueError as exc:
        raise RecordedE0AnalysisError(f"{video_id}: {field}가 정수가 아닙니다: {value!r}") from exc
    if parsed < 0:
        raise RecordedE0AnalysisError(f"{video_id}: {field}는 0 이상이어야 합니다.")
    return parsed


def _max_optional(values: Iterable[float]) -> Optional[float]:
    materialized = list(values)
    return max(materialized) if materialized else None


def _min_optional(values: Iterable[float]) -> Optional[float]:
    materialized = list(values)
    return min(materialized) if materialized else None


def _scenario(video_id: str) -> str:
    parts = video_id.split("_")
    if len(parts) < 7:
        raise RecordedE0AnalysisError(f"Phase 4 video_id 형식이 아닙니다: {video_id}")
    return "_".join(parts[3:-2])


def _longest_run_seconds(
    observations: Sequence[tuple[int, int]], fps: float
) -> float:
    """(frame_number, track_id) 관측의 동일 Track 연속 길이를 초로 반환한다."""
    longest = 0
    by_track = defaultdict(list)
    for frame_number, track_id in observations:
        by_track[track_id].append(frame_number)
    for frame_numbers in by_track.values():
        current = 0
        previous_frame = None
        for frame_number in sorted(set(frame_numbers)):
            is_contiguous = (
                previous_frame is not None and frame_number == previous_frame + 1
            )
            current = current + 1 if is_contiguous else 1
            longest = max(longest, current)
            previous_frame = frame_number
    return longest / fps if fps > 0 else 0.0


def _root_cause(record: dict, config: FallDetectorConfig) -> str:
    if record["label"] == "no_fall":
        return "false_event" if record["event_count"] else "no_false_event"
    if record["timely_detected"]:
        return "timely_detected"
    if (record["track_coverage"] or 0.0) < 0.8:
        return "tracking_limited"
    if record["dynamic_candidate_frame_count"] == 0 and record["matched_model_fall_frames"] == 0:
        return "no_candidate_evidence"
    confirmation_ready = any(
        (
            record["max_horizontal_run_sec"] >= config.fall_confirm_sec,
            record["max_fallen_pose_run_sec"] >= config.fall_confirm_sec,
            record["max_model_fall_run_sec"] >= config.model_confirm_sec,
        )
    )
    if not confirmation_ready:
        return "confirmation_evidence_insufficient"
    return "state_machine_or_track_continuity"


def analyze_video(
    video_id: str,
    evaluation: dict,
    annotation: dict,
    cache_dir: Path,
    config: FallDetectorConfig,
    early_tolerance_sec: float,
    timely_window_sec: float,
    model_iou_threshold: float,
) -> dict:
    cache_path = signal_cache.cache_path_for(cache_dir, video_id)
    metadata, frames = signal_cache.read_video_cache(cache_path, expected_video_id=video_id)
    fps = float(metadata["fps"])
    label = evaluation.get("label")
    if label not in {"fall", "no_fall"}:
        raise RecordedE0AnalysisError(f"{video_id}: label이 올바르지 않습니다: {label}")

    fall_start = _optional_int(annotation.get("fall_start_frame"), "fall_start_frame", video_id)
    if label == "fall":
        if fall_start is None:
            raise RecordedE0AnalysisError(f"{video_id}: fall_start_frame이 필요합니다.")
        window_start = fall_start - round(early_tolerance_sec * fps)
        window_end = fall_start + round(timely_window_sec * fps)
    else:
        window_start = 0
        window_end = len(frames) - 1

    history = MultiTrackHistory(
        fps=fps,
        history_window_sec=config.history_window_sec,
        track_grace_sec=config.track_grace_sec,
    )
    feature_extractor = FallFeatureExtractor()
    pose_extractor = PoseFeatureExtractor()
    features_in_window = []
    pose_values = []
    horizontal_observations = []
    fallen_pose_observations = []
    model_fall_observations = []
    raw_model_fall_frames = set()
    matched_model_fall_frames = set()
    observed_frames = 0

    for cached_frame in frames:
        tracking_result = TrackingResult(
            frame_number=cached_frame.frame_number,
            timestamp=cached_frame.timestamp,
            video_source=video_id,
            tracks=cached_frame.tracks,
        )
        history.update(tracking_result)
        in_window = window_start <= cached_frame.frame_number <= window_end
        if not in_window:
            continue
        observed_frames += 1

        raw_detections = cached_frame.raw_detections or []
        if any(detection.label == "fall" for detection in raw_detections):
            raw_model_fall_frames.add(cached_frame.frame_number)
        evidence = match_detections_to_tracks(
            cached_frame.tracks, raw_detections, model_iou_threshold
        )
        for item in evidence:
            if item.label == "fall":
                matched_model_fall_frames.add(cached_frame.frame_number)
                model_fall_observations.append((cached_frame.frame_number, item.track_id))

        for track in cached_frame.tracks:
            track_history = history.get_history(video_id, track.track_id)
            features = feature_extractor.extract(
                track_history, config.horizontal_aspect_ratio_threshold
            )
            if features is not None:
                features_in_window.append((cached_frame.frame_number, features))
                if features.is_horizontal_posture:
                    horizontal_observations.append(
                        (cached_frame.frame_number, track.track_id)
                    )
            pose = pose_extractor.extract(
                track,
                config.pose_fallen_threshold,
                config.pose_min_keypoint_conf,
            )
            if pose is not None:
                pose_values.append(pose.head_hip_diff_norm)
                if pose.is_fallen_pose:
                    fallen_pose_observations.append(
                        (cached_frame.frame_number, track.track_id)
                    )

    dynamic_frames = {
        frame_number
        for frame_number, features in features_in_window
        if features.track_age_sec >= config.min_track_age_sec
        and (
            features.center_vertical_velocity >= config.fall_center_velocity_threshold
            or features.foot_point_vertical_velocity >= config.fall_foot_velocity_threshold
            or features.height_change_rate <= config.fall_height_shrink_rate_threshold
        )
    }
    record = {
        "video_id": video_id,
        "scenario": _scenario(video_id),
        "label": label,
        "window_start_frame": max(0, window_start),
        "window_end_frame": min(len(frames) - 1, window_end),
        "window_frame_count": observed_frames,
        "event_count": int(evaluation.get("event_count", 0)),
        "timely_detected": bool(evaluation.get("timely_detected")),
        "track_coverage": evaluation.get("track_coverage"),
        "id_switch_count": evaluation.get("id_switch_count"),
        "dynamic_candidate_frame_count": len(dynamic_frames),
        "max_center_vertical_velocity": _max_optional(
            feature.center_vertical_velocity for _, feature in features_in_window
        ),
        "max_foot_vertical_velocity": _max_optional(
            feature.foot_point_vertical_velocity for _, feature in features_in_window
        ),
        "min_height_change_rate": _min_optional(
            feature.height_change_rate for _, feature in features_in_window
        ),
        "max_aspect_ratio": _max_optional(
            feature.aspect_ratio for _, feature in features_in_window
        ),
        "max_head_hip_diff_norm": _max_optional(pose_values),
        "horizontal_posture_frames": len({frame for frame, _ in horizontal_observations}),
        "fallen_pose_frames": len({frame for frame, _ in fallen_pose_observations}),
        "raw_model_fall_frames": len(raw_model_fall_frames),
        "matched_model_fall_frames": len(matched_model_fall_frames),
        "max_horizontal_run_sec": _longest_run_seconds(horizontal_observations, fps),
        "max_fallen_pose_run_sec": _longest_run_seconds(fallen_pose_observations, fps),
        "max_model_fall_run_sec": _longest_run_seconds(model_fall_observations, fps),
    }
    record["diagnostic_class"] = _root_cause(record, config)
    return record


def _finite_values(records: Sequence[dict], field: str) -> list[float]:
    values = [record.get(field) for record in records]
    return [
        float(value)
        for value in values
        if isinstance(value, (int, float)) and math.isfinite(value)
    ]


def _group_summary(records: Sequence[dict]) -> dict:
    fall_records = [record for record in records if record["label"] == "fall"]
    payload = {
        "video_count": len(records),
        "fall_video_count": len(fall_records),
        "timely_detected_count": sum(record["timely_detected"] for record in fall_records),
        "dynamic_candidate_video_count": sum(
            record["dynamic_candidate_frame_count"] > 0 for record in fall_records
        ),
        "horizontal_posture_video_count": sum(
            record["horizontal_posture_frames"] > 0 for record in fall_records
        ),
        "fallen_pose_video_count": sum(
            record["fallen_pose_frames"] > 0 for record in fall_records
        ),
        "model_fall_video_count": sum(
            record["matched_model_fall_frames"] > 0 for record in fall_records
        ),
        "diagnostic_class_counts": dict(
            sorted(Counter(record["diagnostic_class"] for record in records).items())
        ),
    }
    for field in (
        "track_coverage",
        "max_center_vertical_velocity",
        "max_foot_vertical_velocity",
        "min_height_change_rate",
        "max_aspect_ratio",
        "max_head_hip_diff_norm",
    ):
        values = _finite_values(fall_records, field)
        payload[field] = {
            "median": statistics.median(values) if values else None,
            "min": min(values) if values else None,
            "max": max(values) if values else None,
        }
    return payload


def analyze(
    evaluation_path: Path,
    annotations_path: Path,
    cache_dir: Path,
    config_path: Path,
) -> dict:
    evaluation_payload, evaluations = load_evaluation(evaluation_path)
    annotations = load_annotations(annotations_path)
    if set(evaluations) - set(annotations):
        missing = sorted(set(evaluations) - set(annotations))
        raise RecordedE0AnalysisError(f"annotation이 없는 평가 영상이 있습니다: {missing}")

    annotation_sha256 = _sha256_file(annotations_path)
    config_sha256 = _sha256_file(config_path)
    cache_manifest_path = signal_cache.manifest_path_for(cache_dir)
    cache_manifest = _load_json(cache_manifest_path, "cache manifest")
    evaluation_dataset = evaluation_payload.get("dataset")
    cache_dataset = cache_manifest.get("dataset")
    if not isinstance(evaluation_dataset, dict) or not isinstance(cache_dataset, dict):
        raise RecordedE0AnalysisError("evaluation과 cache manifest에 dataset provenance가 필요합니다.")
    if evaluation_dataset != cache_dataset:
        raise RecordedE0AnalysisError("evaluation과 cache manifest의 dataset provenance가 다릅니다.")
    if evaluation_dataset.get("annotations_sha256") != annotation_sha256:
        raise RecordedE0AnalysisError("evaluation의 annotation SHA-256이 실제 파일과 다릅니다.")
    if evaluation_payload.get("config_sha256") != config_sha256:
        raise RecordedE0AnalysisError("evaluation의 config SHA-256이 실제 파일과 다릅니다.")

    config = FallDetectorConfig.from_file(str(config_path))
    run_config = evaluation_payload.get("run_config") or {}
    early_tolerance_sec = float(evaluation_payload.get("early_tolerance_sec", 0.0))
    timely_window_sec = float(evaluation_payload.get("timely_window_sec", 2.0))
    model_iou_threshold = float(run_config.get("fall_model_iou_threshold", 0.3))

    records = [
        analyze_video(
            video_id,
            evaluation,
            annotations[video_id],
            cache_dir,
            config,
            early_tolerance_sec,
            timely_window_sec,
            model_iou_threshold,
        )
        for video_id, evaluation in sorted(evaluations.items())
    ]
    grouped = defaultdict(list)
    for record in records:
        grouped[record["scenario"]].append(record)

    return {
        "schema_version": SCHEMA_VERSION,
        "split": "diagnostic",
        "thresholds": {
            "min_track_age_sec": config.min_track_age_sec,
            "fall_center_velocity_threshold": config.fall_center_velocity_threshold,
            "fall_foot_velocity_threshold": config.fall_foot_velocity_threshold,
            "fall_height_shrink_rate_threshold": config.fall_height_shrink_rate_threshold,
            "horizontal_aspect_ratio_threshold": config.horizontal_aspect_ratio_threshold,
            "pose_fallen_threshold": config.pose_fallen_threshold,
            "fall_confirm_sec": config.fall_confirm_sec,
            "model_confirm_sec": config.model_confirm_sec,
            "model_iou_threshold": model_iou_threshold,
            "early_tolerance_sec": early_tolerance_sec,
            "timely_window_sec": timely_window_sec,
        },
        "summary": _group_summary(records),
        "by_scenario": {
            scenario: _group_summary(items) for scenario, items in sorted(grouped.items())
        },
        "videos": records,
        "sources": {
            "evaluation_sha256": _sha256_file(evaluation_path),
            "annotations_sha256": annotation_sha256,
            "cache_manifest_sha256": _sha256_file(cache_manifest_path),
            "config_sha256": config_sha256,
        },
        "notes": [
            "진단 class는 원인 탐색용 휴리스틱이며 공식 평가 지표가 아니다.",
            "다중 인원 영상의 feature 최댓값은 victim 외 Track을 포함할 수 있다.",
            "test split은 읽거나 평가하지 않는다.",
        ],
    }


def write_output(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with open(temporary, "w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)
        file.write("\n")
    temporary.replace(path)


def main() -> None:
    args = parse_args()
    payload = analyze(
        Path(args.evaluation),
        Path(args.annotations),
        Path(args.cache_dir),
        Path(args.config),
    )
    output = Path(args.output)
    write_output(output, payload)
    summary = payload["summary"]
    print(
        "Phase 4 recorded E0 진단 완료: "
        f"{summary['timely_detected_count']}/{summary['fall_video_count']} timely, "
        f"model fall {summary['model_fall_video_count']}개 영상 -> {output}"
    )


if __name__ == "__main__":
    main()
