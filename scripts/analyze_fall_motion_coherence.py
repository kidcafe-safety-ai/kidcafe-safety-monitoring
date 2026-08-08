"""Cached Fall Event 전후 Track 궤적의 시간적 일관성을 분석한다.

현재 상태머신은 최근 두 Track sample의 동적 근거로 candidate에 진입한 뒤
수평 bbox 또는 fallen Pose의 지속시간으로 Event를 확정한다. 이 도구는
기존 Signal Cache를 재추론 없이 읽어 확정 Event 직전의 다중 sample 궤적을
수치화한다. 임계값을 자동으로 채택하지 않고, 실제 낙상과 검수된 hard-negative
사이에 분리 가능한 coherence feature가 있는지 확인하는 진단 전용 도구다.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import math
import shutil
import statistics
import sys
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Iterable, Mapping, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import fall_signal_cache as cache  # noqa: E402
from real_rgb_cohort import replace_output, sha256_file, write_json, write_text  # noqa: E402


SCHEMA_VERSION = "fall_motion_coherence_v1"
OUTPUT_CSV = "event_motion_coherence.csv"
OUTPUT_JSON = "event_motion_coherence.json"
VALID_LABELS = {"fall", "no_fall"}
VALID_CONFIRM_PATHS = {"bbox", "pose", "model"}
VALID_ENTRY_REASONS = {"dynamic", "model", "handoff"}
METRIC_FIELDS = (
    "visible_frame_ratio",
    "center_downward_step_ratio",
    "foot_downward_step_ratio",
    "height_shrink_step_ratio",
    "center_direction_reversal_count",
    "foot_direction_reversal_count",
    "net_center_descent_norm",
    "net_foot_descent_norm",
    "net_height_change_norm",
    "center_velocity_mean",
    "center_velocity_median",
    "center_velocity_max",
    "center_velocity_stddev",
)
CSV_FIELDS = (
    "video_id",
    "label",
    "event_index",
    "event_frame",
    "track_id",
    "confirm_path",
    "candidate_entry_reason",
    "event_confidence",
    "window_sec",
    "window_start_frame",
    "expected_frame_count",
    "visible_frame_count",
    "motion_pair_count",
    *METRIC_FIELDS,
)


class MotionCoherenceError(ValueError):
    """평가 결과나 Cache가 motion 분석 계약을 만족하지 않을 때 발생한다."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evaluation", required=True, help="cache replay 결과 JSON")
    parser.add_argument("--cache-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument(
        "--window-sec",
        type=float,
        default=0.8,
        help="Event frame을 포함해 소급 분석할 Track 궤적 구간.",
    )
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def _load_json(path: Path, description: str) -> dict:
    if not path.is_file():
        raise MotionCoherenceError(f"{description} 파일이 없습니다: {path}")
    try:
        with open(path, "r", encoding="utf-8") as file:
            payload = json.load(file)
    except (OSError, json.JSONDecodeError) as exc:
        raise MotionCoherenceError(f"{description} JSON을 읽을 수 없습니다: {exc}") from exc
    if not isinstance(payload, dict):
        raise MotionCoherenceError(f"{description} JSON root는 객체여야 합니다.")
    return payload


def load_evaluation(path: Path) -> list[dict]:
    payload = _load_json(path, "evaluation")
    if payload.get("evaluation_valid") is not True:
        raise MotionCoherenceError("evaluation_valid=true인 결과만 분석할 수 있습니다.")
    videos = payload.get("videos")
    if not isinstance(videos, list) or not videos:
        raise MotionCoherenceError("evaluation videos가 비어 있습니다.")

    seen_video_ids = set()
    for video in videos:
        if not isinstance(video, dict):
            raise MotionCoherenceError("evaluation video 항목은 객체여야 합니다.")
        video_id = video.get("video_id")
        if not isinstance(video_id, str) or not video_id or video_id in seen_video_ids:
            raise MotionCoherenceError(f"video_id가 비었거나 중복됩니다: {video_id!r}")
        seen_video_ids.add(video_id)
        if video.get("label") not in VALID_LABELS:
            raise MotionCoherenceError(f"label이 올바르지 않습니다: {video_id}")
        if video.get("error") is not None:
            raise MotionCoherenceError(f"오류 영상이 포함돼 있습니다: {video_id}")
        event_frames = video.get("event_frames")
        diagnostics = video.get("event_diagnostics")
        if not isinstance(event_frames, list) or not isinstance(diagnostics, list):
            raise MotionCoherenceError(f"Event 배열 형식이 잘못됐습니다: {video_id}")
        if video.get("event_count") != len(event_frames):
            raise MotionCoherenceError(f"event_count와 event_frames 수가 다릅니다: {video_id}")
        diagnostic_frames = [item.get("frame_number") for item in diagnostics]
        if sorted(diagnostic_frames) != sorted(event_frames):
            raise MotionCoherenceError(
                f"event_frames와 event_diagnostics가 대응하지 않습니다: {video_id}"
            )
    return videos


def _track_sample(frame_number: int, track) -> dict:
    bbox = track.bbox
    foot_point = track.foot_point
    if len(bbox) != 4 or len(foot_point) != 2:
        raise MotionCoherenceError("Track bbox 또는 foot_point 형식이 올바르지 않습니다.")
    try:
        x1, y1, x2, y2 = (float(value) for value in bbox)
        foot_y = float(foot_point[1])
    except (TypeError, ValueError) as exc:
        raise MotionCoherenceError("Track 좌표가 숫자가 아닙니다.") from exc
    height = y2 - y1
    if not all(math.isfinite(value) for value in (x1, y1, x2, y2, foot_y)) or height <= 0:
        raise MotionCoherenceError("Track 좌표 또는 bbox 높이가 올바르지 않습니다.")
    return {
        "frame_number": frame_number,
        "height": height,
        "center_y": (y1 + y2) / 2.0,
        "foot_y": foot_y,
    }


def _ratio(values: Sequence[float], predicate) -> float:
    if not values:
        raise MotionCoherenceError("motion step이 없어 비율을 계산할 수 없습니다.")
    return sum(bool(predicate(value)) for value in values) / len(values)


def _direction_reversal_count(values: Sequence[float]) -> int:
    """정지(0)는 무시하고, 연속된 양/음 방향 전환만 센다."""
    signs = []
    for value in values:
        if value > 0:
            signs.append(1)
        elif value < 0:
            signs.append(-1)
    return sum(previous != current for previous, current in zip(signs, signs[1:]))


def _summarize_values(values: Sequence[float]) -> dict:
    return {
        "count": len(values),
        "mean": statistics.fmean(values),
        "median": statistics.median(values),
        "min": min(values),
        "max": max(values),
    }


def _group_summary(records: Sequence[Mapping[str, object]]) -> dict:
    payload = {"event_count": len(records)}
    for field in METRIC_FIELDS:
        values = [float(record[field]) for record in records]
        payload[field] = _summarize_values(values)
    return payload


def _analyze_event(
    video: Mapping[str, object],
    diagnostic: Mapping[str, object],
    event_index: int,
    cached_frames: Sequence[cache.CachedFrame],
    fps: float,
    window_sec: float,
) -> dict:
    video_id = str(video["video_id"])
    event_frame = diagnostic.get("frame_number")
    track_id = diagnostic.get("track_id")
    confirm_path = diagnostic.get("confirm_path")
    candidate_reason = diagnostic.get("candidate_entry_reason")
    if not isinstance(event_frame, int) or not 0 <= event_frame < len(cached_frames):
        raise MotionCoherenceError(f"Event frame이 Cache 범위를 벗어납니다: {video_id}")
    if not isinstance(track_id, int):
        raise MotionCoherenceError(f"Event track_id가 올바르지 않습니다: {video_id}")
    if confirm_path not in VALID_CONFIRM_PATHS:
        raise MotionCoherenceError(f"confirm_path가 올바르지 않습니다: {video_id}")
    if candidate_reason not in VALID_ENTRY_REASONS:
        raise MotionCoherenceError(f"candidate_entry_reason이 올바르지 않습니다: {video_id}")

    # MultiTrackHistory._trim_window()와 같은 시간 비교를 쓴다. 단순히
    # event_frame - ceil(window * fps)부터 slice하면 부동소수점 경계에서
    # runtime이 이미 버린 sample을 분석만 포함할 수 있어 gate 임계값과 실제
    # 상태머신 판단이 달라진다.
    event_time_sec = event_frame / fps
    relevant_frames = [
        cached_frame
        for cached_frame in cached_frames
        if cached_frame.frame_number <= event_frame
        and (event_time_sec - cached_frame.frame_number / fps) <= window_sec
    ]
    if not relevant_frames:
        raise MotionCoherenceError(f"Event 직전 window가 비어 있습니다: {video_id}")
    start_frame = relevant_frames[0].frame_number
    samples = []
    for cached_frame in relevant_frames:
        matching_tracks = [
            track for track in cached_frame.tracks if track.track_id == track_id
        ]
        if len(matching_tracks) > 1:
            raise MotionCoherenceError(f"frame 내 track_id가 중복됩니다: {video_id}")
        if matching_tracks:
            samples.append(_track_sample(cached_frame.frame_number, matching_tracks[0]))
    if len(samples) < 2:
        raise MotionCoherenceError(
            f"Event 직전 window에 같은 Track sample이 2개 미만입니다: {video_id}"
        )

    center_velocities = []
    foot_velocities = []
    height_change_rates = []
    for previous, current in zip(samples, samples[1:]):
        delta_frame = current["frame_number"] - previous["frame_number"]
        if delta_frame <= 0:
            raise MotionCoherenceError(f"Track frame 순서가 올바르지 않습니다: {video_id}")
        dt = delta_frame / fps
        height = current["height"]
        center_velocities.append((current["center_y"] - previous["center_y"]) / height / dt)
        foot_velocities.append((current["foot_y"] - previous["foot_y"]) / height / dt)
        height_change_rates.append((height - previous["height"]) / height / dt)

    first = samples[0]
    latest = samples[-1]
    latest_height = latest["height"]
    record = {
        "video_id": video_id,
        "label": video["label"],
        "event_index": event_index,
        "event_frame": event_frame,
        "track_id": track_id,
        "confirm_path": confirm_path,
        "candidate_entry_reason": candidate_reason,
        "event_confidence": diagnostic.get("event_confidence"),
        "window_sec": window_sec,
        "window_start_frame": start_frame,
        "expected_frame_count": len(relevant_frames),
        "visible_frame_count": len(samples),
        "motion_pair_count": len(center_velocities),
        "visible_frame_ratio": len(samples) / len(relevant_frames),
        "center_downward_step_ratio": _ratio(center_velocities, lambda value: value > 0),
        "foot_downward_step_ratio": _ratio(foot_velocities, lambda value: value > 0),
        "height_shrink_step_ratio": _ratio(height_change_rates, lambda value: value < 0),
        "center_direction_reversal_count": _direction_reversal_count(center_velocities),
        "foot_direction_reversal_count": _direction_reversal_count(foot_velocities),
        "net_center_descent_norm": (latest["center_y"] - first["center_y"]) / latest_height,
        "net_foot_descent_norm": (latest["foot_y"] - first["foot_y"]) / latest_height,
        "net_height_change_norm": (latest_height - first["height"]) / latest_height,
        "center_velocity_mean": statistics.fmean(center_velocities),
        "center_velocity_median": statistics.median(center_velocities),
        "center_velocity_max": max(center_velocities),
        "center_velocity_stddev": (
            statistics.pstdev(center_velocities) if len(center_velocities) > 1 else 0.0
        ),
    }
    return record


def analyze(
    evaluation_videos: Sequence[dict], cache_dir: Path, window_sec: float
) -> tuple[list[dict], dict]:
    if not math.isfinite(window_sec) or window_sec <= 0:
        raise MotionCoherenceError("--window-sec은 0보다 큰 유한한 값이어야 합니다.")
    records = []
    for video in evaluation_videos:
        video_id = video["video_id"]
        metadata, cached_frames = cache.read_video_cache(
            cache.cache_path_for(cache_dir, video_id), expected_video_id=video_id
        )
        fps = metadata["fps"]
        diagnostics_by_frame = {
            item["frame_number"]: item for item in video["event_diagnostics"]
        }
        for event_index, event_frame in enumerate(video["event_frames"], start=1):
            records.append(
                _analyze_event(
                    video,
                    diagnostics_by_frame[event_frame],
                    event_index,
                    cached_frames,
                    fps,
                    window_sec,
                )
            )

    by_label = defaultdict(list)
    by_label_and_path = defaultdict(list)
    for record in records:
        by_label[record["label"]].append(record)
        by_label_and_path[(record["label"], record["confirm_path"])].append(record)
    summary = {
        "event_count": len(records),
        "by_label": {
            label: _group_summary(group)
            for label, group in sorted(by_label.items())
        },
        "by_label_and_confirm_path": {
            f"{label}|{path}": _group_summary(group)
            for (label, path), group in sorted(by_label_and_path.items())
        },
    }
    return records, summary


def _render_csv(records: Iterable[Mapping[str, object]]) -> str:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=CSV_FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(records)
    return output.getvalue()


def write_outputs(
    output_dir: Path,
    records: Sequence[Mapping[str, object]],
    summary: Mapping[str, object],
    evaluation_path: Path,
    cache_manifest_path: Path,
    window_sec: float,
    force: bool,
) -> dict:
    if output_dir.exists() and not force:
        raise MotionCoherenceError(f"출력 경로가 이미 있습니다: {output_dir} (--force로 교체)")
    if not cache_manifest_path.is_file():
        raise MotionCoherenceError(f"cache manifest가 없습니다: {cache_manifest_path}")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.build-", dir=output_dir.parent))
    try:
        csv_path = staging / OUTPUT_CSV
        write_text(csv_path, _render_csv(records))
        payload = {
            "schema_version": SCHEMA_VERSION,
            "window_sec": window_sec,
            "summary": summary,
            "sources": {
                "evaluation_path": str(evaluation_path),
                "evaluation_sha256": sha256_file(evaluation_path),
                "cache_dir": str(cache_manifest_path.parent),
                "cache_manifest_sha256": sha256_file(cache_manifest_path),
            },
            "event_motion_coherence_csv_sha256": sha256_file(csv_path),
        }
        write_json(staging / OUTPUT_JSON, payload)
        replace_output(staging, output_dir, force)
        return payload
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def main() -> None:
    args = parse_args()
    evaluation_path = Path(args.evaluation)
    cache_dir = Path(args.cache_dir)
    output_dir = Path(args.output_dir)
    try:
        videos = load_evaluation(evaluation_path)
        records, summary = analyze(videos, cache_dir, args.window_sec)
        payload = write_outputs(
            output_dir,
            records,
            summary,
            evaluation_path,
            cache_dir / "manifest.json",
            args.window_sec,
            args.force,
        )
    except (OSError, MotionCoherenceError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    print(f"Motion coherence 분석: {len(records)} events -> {output_dir}")
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
