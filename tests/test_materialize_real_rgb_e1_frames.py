"""실제 RGB E1 train-only frame supplement 테스트."""

from __future__ import annotations

import csv
import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import materialize_real_rgb_e1_frames as materializer  # noqa: E402
from fall_signal_cache import CachedFrame  # noqa: E402
from src.common.types import Track  # noqa: E402
from src.safety.auxiliary_fall_model import FallDetection  # noqa: E402


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _review_and_analysis(tmp_path: Path) -> tuple[Path, Path]:
    review_path = tmp_path / "review_frozen.csv"
    review_fields = [
        "review_id",
        "review_status",
        "review_decision",
        "selected_for_training",
        "reviewer_id",
    ]
    _write_csv(
        review_path,
        review_fields,
        [
            {
                "review_id": "event_model_confirm",
                "review_status": "reviewed",
                "review_decision": "hard_negative",
                "selected_for_training": "true",
                "reviewer_id": "reviewer-a",
            },
            {
                "review_id": "event_model_entry",
                "review_status": "reviewed",
                "review_decision": "hard_negative",
                "selected_for_training": "true",
                "reviewer_id": "reviewer-a",
            },
            {
                "review_id": "event_rule_only",
                "review_status": "reviewed",
                "review_decision": "hard_negative",
                "selected_for_training": "true",
                "reviewer_id": "reviewer-a",
            },
            {
                "review_id": "event_label_error",
                "review_status": "reviewed",
                "review_decision": "label_error",
                "selected_for_training": "false",
                "reviewer_id": "reviewer-a",
            },
        ],
    )

    analysis_dir = tmp_path / "analysis"
    analysis_path = analysis_dir / "false_events.csv"
    analysis_fields = [
        "review_id",
        "video_id",
        "event_frame",
        "confirm_path",
        "candidate_entry_reason",
        "track_id",
        "split_role",
    ]
    _write_csv(
        analysis_path,
        analysis_fields,
        [
            {
                "review_id": "event_model_confirm",
                "video_id": "video_a",
                "event_frame": 10,
                "confirm_path": "model",
                "candidate_entry_reason": "dynamic",
                "track_id": 1,
                "split_role": "train_candidate",
            },
            {
                "review_id": "event_model_entry",
                "video_id": "video_b",
                "event_frame": 20,
                "confirm_path": "bbox",
                "candidate_entry_reason": "model",
                "track_id": 2,
                "split_role": "train_candidate",
            },
            {
                "review_id": "event_rule_only",
                "video_id": "video_c",
                "event_frame": 30,
                "confirm_path": "bbox",
                "candidate_entry_reason": "dynamic",
                "track_id": 3,
                "split_role": "train_candidate",
            },
            {
                "review_id": "event_label_error",
                "video_id": "video_d",
                "event_frame": 40,
                "confirm_path": "model",
                "candidate_entry_reason": "model",
                "track_id": 4,
                "split_role": "train_candidate",
            },
        ],
    )
    (analysis_dir / "false_event_analysis.json").write_text(
        json.dumps(
            {
                "schema_version": materializer.ANALYSIS_SCHEMA_VERSION,
                "false_events_csv_sha256": _sha256(analysis_path),
            }
        ),
        encoding="utf-8",
    )
    return review_path, analysis_dir


def _track(track_id: int = 1) -> Track:
    return Track(
        track_id=track_id,
        bbox=[10.0, 20.0, 50.0, 80.0],
        foot_point=[30.0, 80.0],
        confidence=0.9,
    )


def _frame(number: int, label: str = "nofall") -> CachedFrame:
    return CachedFrame(
        frame_number=number,
        timestamp=f"00:00:{number:02d}.000",
        tracks=[_track()],
        raw_detections=[
            FallDetection(
                bbox=[10.0, 20.0, 50.0, 80.0],
                label=label,
                confidence=0.9,
            )
        ],
    )


def test_load_selected_events_routes_only_reviewed_model_involved(tmp_path):
    review_path, analysis_dir = _review_and_analysis(tmp_path)

    selected, provenance = materializer.load_selected_events(
        review_path,
        _sha256(review_path),
        analysis_dir,
        expected_event_count=2,
    )

    assert [event.review_id for event in selected] == [
        "event_model_confirm",
        "event_model_entry",
    ]
    assert provenance["selected_model_involved_event_count"] == 2
    assert provenance["review_csv_sha256"] == _sha256(review_path)


def test_load_selected_events_rejects_changed_frozen_review(tmp_path):
    review_path, analysis_dir = _review_and_analysis(tmp_path)

    with pytest.raises(materializer.E1FrameError, match="SHA-256"):
        materializer.load_selected_events(
            review_path,
            "f" * 64,
            analysis_dir,
            expected_event_count=2,
        )


def test_load_selected_events_rejects_unreviewed_training_selection(tmp_path):
    review_path, analysis_dir = _review_and_analysis(tmp_path)
    rows = list(csv.DictReader(review_path.open(encoding="utf-8")))
    rows[0]["review_status"] = "needs_review"
    _write_csv(review_path, list(rows[0]), rows)

    with pytest.raises(materializer.E1FrameError, match="reviewed"):
        materializer.load_selected_events(
            review_path,
            _sha256(review_path),
            analysis_dir,
            expected_event_count=2,
        )


def test_load_selected_events_rejects_validation_training_selection(tmp_path):
    review_path, analysis_dir = _review_and_analysis(tmp_path)
    analysis_path = analysis_dir / "false_events.csv"
    rows = list(csv.DictReader(analysis_path.open(encoding="utf-8")))
    rows[0]["split_role"] = "validation"
    _write_csv(analysis_path, list(rows[0]), rows)
    manifest_path = analysis_dir / "false_event_analysis.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["false_events_csv_sha256"] = _sha256(analysis_path)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(materializer.E1FrameError, match="train_candidate"):
        materializer.load_selected_events(
            review_path,
            _sha256(review_path),
            analysis_dir,
            expected_event_count=2,
        )


def test_select_frames_requires_matched_fall_and_applies_sampling_gap():
    frames = [_frame(number) for number in range(21)]
    for number in (0, 5, 10, 15, 20):
        frames[number] = _frame(number, label="fall")
    event = materializer.SelectedEvent(
        review_id="event_model",
        video_id="video_a",
        event_frame=10,
        track_id=1,
        confirm_path="model",
        candidate_entry_reason="dynamic",
    )

    selected = materializer.select_frames_for_event(
        event,
        frames,
        fps=10.0,
        window_sec=1.0,
        sample_fps=2.0,
        iou_threshold=0.3,
        max_frames=7,
    )

    assert [frame.frame_number for frame in selected] == [0, 5, 10, 15, 20]
    assert all(frame.fall_track_ids == (1,) for frame in selected)


def test_select_frames_rejects_model_event_without_fall_detection():
    frames = [_frame(number) for number in range(11)]
    event = materializer.SelectedEvent(
        review_id="event_model",
        video_id="video_a",
        event_frame=5,
        track_id=1,
        confirm_path="model",
        candidate_entry_reason="model",
    )

    with pytest.raises(materializer.E1FrameError, match="fall detection"):
        materializer.select_frames_for_event(
            event,
            frames,
            fps=10.0,
            window_sec=0.5,
            sample_fps=2.0,
            iou_threshold=0.3,
            max_frames=7,
        )


def test_select_frames_ignores_fall_detection_for_another_track():
    frame = CachedFrame(
        frame_number=0,
        timestamp="00:00:00.000",
        tracks=[_track(track_id=2)],
        raw_detections=[
            FallDetection(
                bbox=[10.0, 20.0, 50.0, 80.0],
                label="fall",
                confidence=0.9,
            )
        ],
    )
    event = materializer.SelectedEvent(
        review_id="event_model",
        video_id="video_a",
        event_frame=0,
        track_id=1,
        confirm_path="model",
        candidate_entry_reason="model",
    )

    with pytest.raises(materializer.E1FrameError, match="fall detection"):
        materializer.select_frames_for_event(
            event,
            [frame],
            fps=10.0,
            window_sec=1.0,
            sample_fps=2.0,
            iou_threshold=0.3,
            max_frames=7,
        )


def test_label_text_writes_nofall_yolo_bbox():
    content, track_ids = materializer._label_text([_track()], 100, 100)

    assert track_ids == [1]
    assert content == "0 0.30000000 0.50000000 0.40000000 0.60000000\n"


def test_validate_cache_manifest_checks_split_and_model(tmp_path):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    model_sha256 = "a" * 64
    (cache_dir / "manifest.json").write_text(
        json.dumps(
            {
                "split": "",
                "auxiliary_model": {"model_sha256": model_sha256},
            }
        ),
        encoding="utf-8",
    )

    manifest = materializer.validate_cache_manifest(
        cache_dir, model_sha256, expected_cache_split=""
    )

    assert manifest["split"] == ""
    with pytest.raises(materializer.E1FrameError, match="cache split"):
        materializer.validate_cache_manifest(
            cache_dir, model_sha256, expected_cache_split="validation"
        )


def test_rejects_invalid_sampling_settings():
    event = materializer.SelectedEvent(
        review_id="event_model",
        video_id="video_a",
        event_frame=0,
        track_id=1,
        confirm_path="model",
        candidate_entry_reason="model",
    )

    with pytest.raises(materializer.E1FrameError, match="sample-fps"):
        materializer.select_frames_for_event(
            event,
            [_frame(0, "fall")],
            fps=10.0,
            window_sec=1.0,
            sample_fps=20.0,
            iou_threshold=0.3,
            max_frames=7,
        )
