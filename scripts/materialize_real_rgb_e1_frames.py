r"""동결 검수된 실제 RGB train-candidate 오탐에서 E1 nofall 프레임을 만든다.

검수자가 ``hard_negative``로 확정하고 학습 사용을 승인한 Event 중 보조 모델이
후보 진입 또는 확정에 관여한 Event만 사용한다. Event 전후의 Signal Cache에서
실제로 ``fall`` detection이 Track과 매칭된 frame만 3 FPS 이하로 선별하고,
검증된 H.264 영상에서 lossless PNG와 YOLO class 0(nofall) bbox를 만든다.

Validation/test 결과는 입력으로 받지 않는다. 출력은 기존 CAUCAFall 학습
데이터에 합치기 전의 train-only supplement이며, 원본 영상·cache·이미지는
Git에 올리지 않는다.

Usage:
    python scripts/materialize_real_rgb_e1_frames.py \
        --review-csv outputs/phase4_real_rgb/review_frozen_<sha>.csv \
        --expected-review-sha256 <sha256> \
        --analysis-dir outputs/phase4_real_rgb/train_false_event_analysis \
        --cohort-dir outputs/phase4_real_rgb/up_fall_camera1_trial1 \
        --cache-dir outputs/phase4_real_rgb/cache/up_fall_train_e0 \
        --expected-cache-split "" \
        --expected-model-sha256 <fall_detector_v1_sha256> \
        --expected-event-count 45 \
        --output-dir outputs/phase4_real_rgb/up_fall_e1_frames
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import re
import shutil
import sys
import tempfile
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fall_signal_cache as signal_cache  # noqa: E402
from src.common.types import Track  # noqa: E402
from src.safety.fall_model_matching import (  # noqa: E402
    match_detections_to_tracks,
)


SCHEMA_VERSION = "real_rgb_e1_frame_supplement_v1"
ANALYSIS_SCHEMA_VERSION = "real_rgb_false_event_analysis_v1"
COHORT_SCHEMA_VERSION = "real_rgb_fall_cohort_v1"
REVIEW_DECISION = "hard_negative"
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
REQUIRED_REVIEW_COLUMNS = {
    "review_id",
    "review_status",
    "review_decision",
    "selected_for_training",
    "reviewer_id",
}
REQUIRED_ANALYSIS_COLUMNS = {
    "review_id",
    "video_id",
    "event_frame",
    "confirm_path",
    "candidate_entry_reason",
    "track_id",
    "split_role",
}


class E1FrameError(ValueError):
    """검수·cache·영상 또는 출력 계약이 깨졌을 때 발생한다."""


@dataclass(frozen=True)
class SelectedEvent:
    review_id: str
    video_id: str
    event_frame: int
    track_id: int
    confirm_path: str
    candidate_entry_reason: str


@dataclass(frozen=True)
class SelectedFrame:
    review_id: str
    video_id: str
    event_frame: int
    frame_number: int
    fall_track_ids: Tuple[int, ...]
    tracks: Tuple[Track, ...]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review-csv", required=True)
    parser.add_argument("--expected-review-sha256", required=True)
    parser.add_argument("--analysis-dir", required=True)
    parser.add_argument("--cohort-dir", required=True)
    parser.add_argument("--cache-dir", required=True)
    parser.add_argument(
        "--expected-cache-split",
        default="",
        help="Train mining cache manifest에 기록된 split의 정확한 값",
    )
    parser.add_argument("--expected-model-sha256", required=True)
    parser.add_argument("--expected-event-count", type=int, required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--window-sec", type=float, default=1.0)
    parser.add_argument("--sample-fps", type=float, default=3.0)
    parser.add_argument("--iou-threshold", type=float, default=0.3)
    parser.add_argument("--max-frames-per-event", type=int, default=7)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as file:
        for chunk in iter(lambda: file.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _valid_sha256(value: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-f]{64}", value))


def _load_json(path: Path, description: str) -> dict:
    if not path.is_file():
        raise E1FrameError(f"{description} 파일이 없습니다: {path}")
    try:
        with open(path, "r", encoding="utf-8") as file:
            payload = json.load(file)
    except (OSError, json.JSONDecodeError) as exc:
        raise E1FrameError(f"{description} JSON을 읽을 수 없습니다: {exc}") from exc
    if not isinstance(payload, dict):
        raise E1FrameError(f"{description} JSON root는 객체여야 합니다.")
    return payload


def _load_csv(path: Path, required: set[str], description: str) -> List[dict]:
    if not path.is_file():
        raise E1FrameError(f"{description} CSV가 없습니다: {path}")
    with open(path, "r", encoding="utf-8", newline="") as file:
        reader = csv.DictReader(file)
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise E1FrameError(
                f"{description} CSV에 필수 컬럼이 없습니다: {sorted(missing)}"
            )
        return list(reader)


def _parse_bool(value: object, field: str, row_number: int) -> bool:
    normalized = str(value).strip().lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise E1FrameError(
        f"review.csv:{row_number}의 {field}는 true/false여야 합니다: {value!r}"
    )


def load_selected_events(
    review_path: Path,
    expected_review_sha256: str,
    analysis_dir: Path,
    expected_event_count: int,
) -> tuple[List[SelectedEvent], dict]:
    if expected_event_count <= 0:
        raise E1FrameError("expected-event-count는 1 이상이어야 합니다.")
    if not _valid_sha256(expected_review_sha256):
        raise E1FrameError("expected-review-sha256은 소문자 SHA-256이어야 합니다.")
    actual_review_sha256 = _sha256(review_path)
    if actual_review_sha256 != expected_review_sha256:
        raise E1FrameError(
            "동결 review CSV SHA-256이 다릅니다: "
            f"expected={expected_review_sha256}, actual={actual_review_sha256}"
        )

    review_rows = _load_csv(
        review_path, REQUIRED_REVIEW_COLUMNS, "frozen review"
    )
    analysis_manifest_path = analysis_dir / "false_event_analysis.json"
    analysis_csv_path = analysis_dir / "false_events.csv"
    analysis_manifest = _load_json(analysis_manifest_path, "analysis manifest")
    if analysis_manifest.get("schema_version") != ANALYSIS_SCHEMA_VERSION:
        raise E1FrameError("지원하지 않는 analysis schema_version입니다.")
    if analysis_manifest.get("false_events_csv_sha256") != _sha256(
        analysis_csv_path
    ):
        raise E1FrameError("analysis CSV SHA-256이 manifest와 다릅니다.")
    analysis_rows = _load_csv(
        analysis_csv_path, REQUIRED_ANALYSIS_COLUMNS, "analysis"
    )
    analysis_by_id = {}
    for row in analysis_rows:
        review_id = (row.get("review_id") or "").strip()
        if not SAFE_ID.fullmatch(review_id) or review_id in analysis_by_id:
            raise E1FrameError(f"analysis review_id가 비었거나 중복됩니다: {review_id!r}")
        analysis_by_id[review_id] = row

    seen_review_ids = set()
    selected = []
    for row_number, row in enumerate(review_rows, start=2):
        review_id = (row.get("review_id") or "").strip()
        if not SAFE_ID.fullmatch(review_id) or review_id in seen_review_ids:
            raise E1FrameError(
                f"review.csv:{row_number}의 review_id가 비었거나 중복됩니다."
            )
        seen_review_ids.add(review_id)
        selected_for_training = _parse_bool(
            row.get("selected_for_training"), "selected_for_training", row_number
        )
        if not selected_for_training:
            continue
        if (row.get("review_status") or "").strip() != "reviewed":
            raise E1FrameError(f"학습 선택 행이 reviewed가 아닙니다: {review_id}")
        if (row.get("review_decision") or "").strip() != REVIEW_DECISION:
            raise E1FrameError(f"학습 선택 행이 hard_negative가 아닙니다: {review_id}")
        if not (row.get("reviewer_id") or "").strip():
            raise E1FrameError(f"학습 선택 행의 reviewer_id가 비었습니다: {review_id}")
        analysis = analysis_by_id.get(review_id)
        if analysis is None:
            raise E1FrameError(f"analysis에 review_id가 없습니다: {review_id}")
        if (analysis.get("split_role") or "").strip() != "train_candidate":
            raise E1FrameError(
                f"학습 선택 행은 train_candidate여야 합니다: {review_id}"
            )
        confirm_path = (analysis.get("confirm_path") or "").strip()
        candidate_reason = (analysis.get("candidate_entry_reason") or "").strip()
        if confirm_path != "model" and candidate_reason != "model":
            continue
        try:
            event_frame = int(analysis["event_frame"])
            track_id = int(analysis["track_id"])
        except (TypeError, ValueError) as exc:
            raise E1FrameError(
                f"analysis event_frame/track_id가 올바르지 않습니다: {review_id}"
            ) from exc
        if event_frame < 0 or track_id < 0:
            raise E1FrameError(
                f"analysis event_frame/track_id가 음수입니다: {review_id}"
            )
        video_id = (analysis.get("video_id") or "").strip()
        if not SAFE_ID.fullmatch(video_id):
            raise E1FrameError(f"analysis video_id가 올바르지 않습니다: {video_id!r}")
        selected.append(
            SelectedEvent(
                review_id=review_id,
                video_id=video_id,
                event_frame=event_frame,
                track_id=track_id,
                confirm_path=confirm_path,
                candidate_entry_reason=candidate_reason,
            )
        )

    if seen_review_ids != set(analysis_by_id):
        raise E1FrameError(
            "frozen review와 analysis의 review_id 집합이 다릅니다."
        )
    if len(selected) != expected_event_count:
        raise E1FrameError(
            "model-involved Event 수가 예상과 다릅니다: "
            f"expected={expected_event_count}, actual={len(selected)}"
        )
    if len({event.review_id for event in selected}) != len(selected):
        raise E1FrameError("선택된 review_id가 중복됩니다.")
    return selected, {
        "review_csv_sha256": actual_review_sha256,
        "analysis_manifest_sha256": _sha256(analysis_manifest_path),
        "analysis_csv_sha256": _sha256(analysis_csv_path),
        "reviewed_row_count": len(review_rows),
        "selected_model_involved_event_count": len(selected),
    }


def validate_cache_manifest(
    cache_dir: Path,
    expected_model_sha256: str,
    expected_cache_split: str,
) -> dict:
    if not _valid_sha256(expected_model_sha256):
        raise E1FrameError("expected-model-sha256은 소문자 SHA-256이어야 합니다.")
    manifest_path = cache_dir / "manifest.json"
    manifest = _load_json(manifest_path, "cache manifest")
    if manifest.get("split") != expected_cache_split:
        raise E1FrameError(
            "cache split이 기대값과 다릅니다: "
            f"expected={expected_cache_split!r}, actual={manifest.get('split')!r}"
        )
    auxiliary_model = manifest.get("auxiliary_model")
    if not isinstance(auxiliary_model, dict):
        raise E1FrameError("cache manifest에 auxiliary_model이 없습니다.")
    actual_model_sha256 = auxiliary_model.get("model_sha256")
    if actual_model_sha256 != expected_model_sha256:
        raise E1FrameError(
            "cache 보조 모델 SHA-256이 기대값과 다릅니다: "
            f"{actual_model_sha256!r}"
        )
    return manifest


def _fall_track_ids(frame: signal_cache.CachedFrame, iou_threshold: float) -> set[int]:
    if frame.raw_detections is None:
        raise E1FrameError("보조 모델 detection이 없는 cache는 E1에 사용할 수 없습니다.")
    evidence = match_detections_to_tracks(
        frame.tracks, frame.raw_detections, iou_threshold
    )
    return {item.track_id for item in evidence if item.label == "fall"}


def select_frames_for_event(
    event: SelectedEvent,
    frames: Sequence[signal_cache.CachedFrame],
    fps: float,
    window_sec: float,
    sample_fps: float,
    iou_threshold: float,
    max_frames: int,
) -> List[SelectedFrame]:
    if not math.isfinite(window_sec) or window_sec <= 0:
        raise E1FrameError("window-sec은 0보다 큰 유한한 값이어야 합니다.")
    if not math.isfinite(sample_fps) or sample_fps <= 0 or sample_fps > fps:
        raise E1FrameError("sample-fps는 0보다 크고 원본 FPS 이하여야 합니다.")
    if not 0 < iou_threshold <= 1:
        raise E1FrameError("iou-threshold는 0보다 크고 1 이하여야 합니다.")
    if max_frames <= 0:
        raise E1FrameError("max-frames-per-event는 1 이상이어야 합니다.")

    radius = int(math.ceil(window_sec * fps))
    start = max(0, event.event_frame - radius)
    end = min(len(frames) - 1, event.event_frame + radius)
    candidates = []
    for frame_number in range(start, end + 1):
        frame = frames[frame_number]
        fall_track_ids = _fall_track_ids(frame, iou_threshold)
        if event.track_id not in fall_track_ids:
            continue
        candidates.append((frame, tuple(sorted(fall_track_ids))))

    minimum_gap = max(1, int(math.ceil(fps / sample_fps)))
    selected: List[SelectedFrame] = []
    for frame, fall_track_ids in sorted(
        candidates,
        key=lambda item: (abs(item[0].frame_number - event.event_frame), item[0].frame_number),
    ):
        if any(
            abs(frame.frame_number - item.frame_number) < minimum_gap
            for item in selected
        ):
            continue
        selected.append(
            SelectedFrame(
                review_id=event.review_id,
                video_id=event.video_id,
                event_frame=event.event_frame,
                frame_number=frame.frame_number,
                fall_track_ids=fall_track_ids,
                tracks=tuple(frame.tracks),
            )
        )
        if len(selected) == max_frames:
            break
    if not selected:
        raise E1FrameError(
            f"Event window에 매칭된 fall detection이 없습니다: {event.review_id}"
        )
    return sorted(selected, key=lambda item: item.frame_number)


def select_training_frames(
    events: Sequence[SelectedEvent],
    cache_dir: Path,
    window_sec: float,
    sample_fps: float,
    iou_threshold: float,
    max_frames_per_event: int,
) -> tuple[List[SelectedFrame], Dict[str, dict]]:
    events_by_video: Dict[str, List[SelectedEvent]] = defaultdict(list)
    for event in events:
        events_by_video[event.video_id].append(event)

    selected_by_key: Dict[Tuple[str, int], SelectedFrame] = {}
    cache_metadata = {}
    for video_id, video_events in sorted(events_by_video.items()):
        cache_path = signal_cache.cache_path_for(cache_dir, video_id)
        try:
            metadata, frames = signal_cache.read_video_cache(
                cache_path, expected_video_id=video_id
            )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise E1FrameError(f"cache를 읽을 수 없습니다: {video_id}: {exc}") from exc
        fps = float(metadata["fps"])
        cache_metadata[video_id] = metadata
        for event in video_events:
            for selected in select_frames_for_event(
                event,
                frames,
                fps,
                window_sec,
                sample_fps,
                iou_threshold,
                max_frames_per_event,
            ):
                key = selected.video_id, selected.frame_number
                existing = selected_by_key.get(key)
                if existing is None:
                    selected_by_key[key] = selected
                else:
                    selected_by_key[key] = SelectedFrame(
                        review_id="|".join(
                            sorted(set(existing.review_id.split("|")) | {selected.review_id})
                        ),
                        video_id=selected.video_id,
                        event_frame=min(existing.event_frame, selected.event_frame),
                        frame_number=selected.frame_number,
                        fall_track_ids=tuple(
                            sorted(set(existing.fall_track_ids) | set(selected.fall_track_ids))
                        ),
                        tracks=existing.tracks,
                    )
    return [selected_by_key[key] for key in sorted(selected_by_key)], cache_metadata


def _safe_video_path(value: object) -> Path:
    if not isinstance(value, str) or not value or "\\" in value:
        raise E1FrameError(f"video_path가 올바르지 않습니다: {value!r}")
    pure = PurePosixPath(value)
    if (
        pure.is_absolute()
        or ".." in pure.parts
        or "." in pure.parts
        or not pure.parts
        or pure.parts[0] != "videos"
        or pure.suffix.lower() != ".mp4"
    ):
        raise E1FrameError(f"안전하지 않은 video_path입니다: {value!r}")
    return Path(*pure.parts)


def load_cohort(cohort_dir: Path) -> tuple[Dict[str, dict], dict, Path]:
    manifest_path = cohort_dir / "cohort_manifest.json"
    manifest = _load_json(manifest_path, "cohort manifest")
    if manifest.get("schema_version") != COHORT_SCHEMA_VERSION:
        raise E1FrameError("지원하지 않는 cohort schema_version입니다.")
    records = manifest.get("videos")
    if not isinstance(records, list) or manifest.get("video_count") != len(records):
        raise E1FrameError("cohort manifest videos/video_count가 올바르지 않습니다.")
    by_id = {}
    for record in records:
        video_id = record.get("video_id") if isinstance(record, dict) else None
        if not isinstance(video_id, str) or not SAFE_ID.fullmatch(video_id):
            raise E1FrameError(f"cohort video_id가 올바르지 않습니다: {video_id!r}")
        if video_id in by_id:
            raise E1FrameError(f"cohort video_id가 중복됩니다: {video_id}")
        relative_path = _safe_video_path(record.get("video_path"))
        video_path = cohort_dir / relative_path
        if not video_path.is_file():
            raise E1FrameError(f"H.264 영상이 없습니다: {video_path}")
        by_id[video_id] = {
            "path": video_path,
            "relative_path": relative_path.as_posix(),
            "sha256": record.get("output_sha256"),
            "split_role": record.get("split_role"),
        }
    return by_id, manifest, manifest_path


def _normalized_bbox(track: Track, width: int, height: int) -> Optional[Tuple[float, ...]]:
    x1, y1, x2, y2 = map(float, track.bbox)
    x1 = min(max(x1, 0.0), float(width))
    x2 = min(max(x2, 0.0), float(width))
    y1 = min(max(y1, 0.0), float(height))
    y2 = min(max(y2, 0.0), float(height))
    if x2 <= x1 or y2 <= y1:
        return None
    return (
        ((x1 + x2) / 2.0) / width,
        ((y1 + y2) / 2.0) / height,
        (x2 - x1) / width,
        (y2 - y1) / height,
    )


def _label_text(tracks: Iterable[Track], width: int, height: int) -> tuple[str, List[int]]:
    rows = []
    track_ids = []
    seen = set()
    for track in sorted(tracks, key=lambda item: item.track_id):
        if track.track_id in seen:
            continue
        seen.add(track.track_id)
        bbox = _normalized_bbox(track, width, height)
        if bbox is None:
            continue
        rows.append("0 " + " ".join(f"{value:.8f}" for value in bbox))
        track_ids.append(track.track_id)
    if not rows:
        raise E1FrameError("선택 frame에 유효한 Track bbox가 없습니다.")
    return "\n".join(rows) + "\n", track_ids


def _decode_selected_frames(
    selected_frames: Sequence[SelectedFrame],
    cohort: Mapping[str, dict],
    staging_dir: Path,
) -> List[dict]:
    by_video: Dict[str, Dict[int, SelectedFrame]] = defaultdict(dict)
    for selected in selected_frames:
        by_video[selected.video_id][selected.frame_number] = selected

    records = []
    for video_id, selected_by_number in sorted(by_video.items()):
        source = cohort.get(video_id)
        if source is None:
            raise E1FrameError(f"H.264 cohort에 video_id가 없습니다: {video_id}")
        if source["sha256"] != _sha256(source["path"]):
            raise E1FrameError(f"H.264 영상 SHA-256이 다릅니다: {source['path']}")
        capture = cv2.VideoCapture(str(source["path"]))
        if not capture.isOpened():
            raise E1FrameError(f"H.264 영상을 열 수 없습니다: {source['path']}")
        needed = set(selected_by_number)
        max_frame = max(needed)
        frame_number = 0
        try:
            while frame_number <= max_frame:
                ok, image = capture.read()
                if not ok:
                    break
                selected = selected_by_number.get(frame_number)
                if selected is not None:
                    height, width = image.shape[:2]
                    label_text, track_ids = _label_text(
                        selected.tracks, width, height
                    )
                    sample_id = f"{video_id}_f{frame_number:06d}"
                    image_path = staging_dir / "images" / "train" / f"{sample_id}.png"
                    label_path = staging_dir / "labels" / "train" / f"{sample_id}.txt"
                    image_path.parent.mkdir(parents=True, exist_ok=True)
                    label_path.parent.mkdir(parents=True, exist_ok=True)
                    if not cv2.imwrite(str(image_path), image):
                        raise E1FrameError(f"PNG 저장에 실패했습니다: {image_path}")
                    label_path.write_text(label_text, encoding="ascii")
                    records.append(
                        {
                            "sample_id": sample_id,
                            "review_ids": selected.review_id,
                            "video_id": video_id,
                            "event_frame": selected.event_frame,
                            "frame_number": frame_number,
                            "source_video_path": source["relative_path"],
                            "fall_track_ids": "|".join(map(str, selected.fall_track_ids)),
                            "labeled_track_ids": "|".join(map(str, track_ids)),
                            "image_path": f"images/train/{sample_id}.png",
                            "label_path": f"labels/train/{sample_id}.txt",
                            "image_sha256": _sha256(image_path),
                            "label_sha256": _sha256(label_path),
                        }
                    )
                    needed.remove(frame_number)
                if not needed:
                    break
                frame_number += 1
        finally:
            capture.release()
        if needed:
            raise E1FrameError(
                f"영상에서 선택 frame을 읽지 못했습니다: {video_id}: {sorted(needed)}"
            )
    return sorted(records, key=lambda row: row["sample_id"])


def _index_text(records: Sequence[dict]) -> str:
    fields = [
        "sample_id",
        "review_ids",
        "video_id",
        "event_frame",
        "frame_number",
        "source_video_path",
        "fall_track_ids",
        "labeled_track_ids",
        "image_path",
        "label_path",
        "image_sha256",
        "label_sha256",
    ]
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(records)
    return output.getvalue()


def _replace_output(staging_dir: Path, output_dir: Path, force: bool) -> None:
    if output_dir.exists() and not force:
        raise E1FrameError(f"{output_dir}가 이미 있습니다 (--force로 전체 교체).")
    backup = output_dir.with_name(f".{output_dir.name}.backup-{os.getpid()}")
    if output_dir.exists():
        output_dir.rename(backup)
    try:
        staging_dir.rename(output_dir)
    except Exception:
        if backup.exists() and not output_dir.exists():
            backup.rename(output_dir)
        raise
    shutil.rmtree(backup, ignore_errors=True)


def materialize(
    review_path: Path,
    expected_review_sha256: str,
    analysis_dir: Path,
    cohort_dir: Path,
    cache_dir: Path,
    expected_cache_split: str,
    expected_model_sha256: str,
    expected_event_count: int,
    output_dir: Path,
    window_sec: float,
    sample_fps: float,
    iou_threshold: float,
    max_frames_per_event: int,
    force: bool,
) -> dict:
    events, review_provenance = load_selected_events(
        review_path,
        expected_review_sha256,
        analysis_dir,
        expected_event_count,
    )
    cache_manifest = validate_cache_manifest(
        cache_dir, expected_model_sha256, expected_cache_split
    )
    selected_frames, cache_metadata = select_training_frames(
        events,
        cache_dir,
        window_sec,
        sample_fps,
        iou_threshold,
        max_frames_per_event,
    )
    cohort, cohort_manifest, cohort_manifest_path = load_cohort(cohort_dir)
    for event in events:
        cohort_video = cohort.get(event.video_id)
        if cohort_video is None:
            raise E1FrameError(f"H.264 cohort에 video_id가 없습니다: {event.video_id}")
        if cohort_video.get("split_role") != "train_candidate":
            raise E1FrameError(
                f"학습 선택 영상은 train_candidate여야 합니다: {event.video_id}"
            )

    output_dir.parent.mkdir(parents=True, exist_ok=True)
    staging_dir = Path(
        tempfile.mkdtemp(prefix=f".{output_dir.name}.build-", dir=output_dir.parent)
    )
    try:
        records = _decode_selected_frames(selected_frames, cohort, staging_dir)
        index_content = _index_text(records)
        index_path = staging_dir / "frames.csv"
        index_path.write_text(index_content, encoding="utf-8", newline="")
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "purpose": "train-only E1 nofall supplement",
            "source_split_role": "train_candidate",
            "class_mapping": {"0": "nofall", "1": "fall"},
            "policy": {
                "review_decision": REVIEW_DECISION,
                "model_involved": (
                    "confirm_path=model OR candidate_entry_reason=model"
                ),
                "window_sec": window_sec,
                "sample_fps_max": sample_fps,
                "iou_threshold": iou_threshold,
                "max_frames_per_event": max_frames_per_event,
                "bbox_source": "PoseTracker tracks",
                "frame_condition": "matched auxiliary label=fall",
            },
            "sources": {
                **review_provenance,
                "source_dataset": cohort_manifest.get("source_dataset"),
                "review_csv_path": str(review_path),
                "cache_manifest_sha256": _sha256(cache_dir / "manifest.json"),
                "cache_split": cache_manifest["split"],
                "cohort_manifest_sha256": _sha256(cohort_manifest_path),
                "auxiliary_model_sha256": cache_manifest["auxiliary_model"][
                    "model_sha256"
                ],
            },
            "selected_event_count": len(events),
            "selected_video_count": len({event.video_id for event in events}),
            "frame_count": len(records),
            "video_count": len({row["video_id"] for row in records}),
            "frames_csv_sha256": hashlib.sha256(
                index_content.encode("utf-8")
            ).hexdigest(),
            "cache_video_metadata": {
                video_id: {
                    "fps": metadata["fps"],
                    "frame_count": metadata["frame_count"],
                }
                for video_id, metadata in sorted(cache_metadata.items())
            },
        }
        manifest_path = staging_dir / "supplement_manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        _replace_output(staging_dir, output_dir, force)
        return manifest
    except Exception:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise


def main() -> None:
    args = parse_args()
    try:
        manifest = materialize(
            review_path=Path(args.review_csv),
            expected_review_sha256=args.expected_review_sha256,
            analysis_dir=Path(args.analysis_dir),
            cohort_dir=Path(args.cohort_dir),
            cache_dir=Path(args.cache_dir),
            expected_cache_split=args.expected_cache_split,
            expected_model_sha256=args.expected_model_sha256,
            expected_event_count=args.expected_event_count,
            output_dir=Path(args.output_dir),
            window_sec=args.window_sec,
            sample_fps=args.sample_fps,
            iou_threshold=args.iou_threshold,
            max_frames_per_event=args.max_frames_per_event,
            force=args.force,
        )
    except E1FrameError as exc:
        raise SystemExit(str(exc)) from exc
    print(
        f"실제 RGB E1 supplement: {manifest['selected_event_count']} events / "
        f"{manifest['frame_count']} frames -> {args.output_dir}"
    )


if __name__ == "__main__":
    main()
