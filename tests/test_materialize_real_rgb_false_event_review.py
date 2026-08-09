"""실제 RGB false Event 검수 clip 생성 도구 테스트."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import materialize_real_rgb_false_event_review as review  # noqa: E402


def _analysis(tmp_path: Path, *, end_sec: float = 3.5) -> Path:
    root = tmp_path / "analysis"
    root.mkdir()
    fields = [
        "review_id",
        "source_dataset",
        "video_id",
        "subject_id",
        "activity_name",
        "active_labels",
        "event_frame",
        "event_sec",
        "review_start_sec",
        "review_end_sec",
        "confirm_path",
        "candidate_entry_reason",
        "diagnostic_route",
    ]
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerow(
        {
            "review_id": "upfall_s09_event_01",
            "source_dataset": "UP-Fall",
            "video_id": "upfall_s09",
            "subject_id": 9,
            "activity_name": "laying",
            "active_labels": "laying",
            "event_frame": 36,
            "event_sec": 2.0,
            "review_start_sec": 0.5,
            "review_end_sec": end_sec,
            "confirm_path": "model",
            "candidate_entry_reason": "dynamic",
            "diagnostic_route": "aux_model_involved",
        }
    )
    csv_content = output.getvalue()
    (root / "false_events.csv").write_text(csv_content, encoding="utf-8")
    (root / "false_event_analysis.json").write_text(
        json.dumps(
            {
                "schema_version": "real_rgb_false_event_analysis_v1",
                "false_events_csv_sha256": hashlib.sha256(
                    csv_content.encode()
                ).hexdigest(),
                "summary": {"false_event_count": 1},
            }
        ),
        encoding="utf-8",
    )
    return root


def _cohort(tmp_path: Path) -> Path:
    root = tmp_path / "cohort"
    video = root / "videos/validation/upfall_s09.mp4"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"h264-video")
    manifest = {
        "schema_version": "real_rgb_fall_cohort_v1",
        "source_dataset": "UP-Fall",
        "video_count": 1,
        "videos": [
            {
                "video_id": "upfall_s09",
                "video_path": "videos/validation/upfall_s09.mp4",
                "output_sha256": hashlib.sha256(video.read_bytes()).hexdigest(),
                "output_probe": {"duration_sec": 5.0},
            }
        ],
    }
    (root / "cohort_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return root


def _fake_clip_tools(monkeypatch):
    monkeypatch.setattr(review.shutil, "which", lambda value: f"/usr/bin/{value}")

    def fake_clip(source, destination, start, duration, ffmpeg, crf, preset):
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"review-clip")

    monkeypatch.setattr(review, "run_clip", fake_clip)


def test_materializes_review_package(tmp_path, monkeypatch):
    _fake_clip_tools(monkeypatch)
    output = tmp_path / "review"

    manifest = review.materialize_review(
        _analysis(tmp_path),
        _cohort(tmp_path),
        output,
        "ffmpeg",
        20,
        "veryfast",
        False,
    )

    assert manifest["schema_version"] == "real_rgb_false_event_review_v1"
    assert manifest["clip_count"] == 1
    assert manifest["review_decisions"] == [
        "ambiguous",
        "hard_negative",
        "label_error",
        "tracking_error",
    ]
    review_csv = (output / "review.csv").read_text()
    assert "upfall_s09_event_01" in review_csv
    assert ",pending,,false,," in review_csv
    assert (output / "clips/upfall_s09_event_01.mp4").is_file()


def test_rejects_tampered_analysis_csv(tmp_path):
    analysis = _analysis(tmp_path)
    (analysis / "false_events.csv").write_text("tampered", encoding="utf-8")

    with pytest.raises(review.ReviewPackageError, match="SHA-256"):
        review.load_analysis(analysis)


def test_rejects_review_window_past_video_duration(tmp_path, monkeypatch):
    _fake_clip_tools(monkeypatch)

    with pytest.raises(review.ReviewPackageError, match="duration"):
        review.materialize_review(
            _analysis(tmp_path, end_sec=5.2),
            _cohort(tmp_path),
            tmp_path / "review",
            "ffmpeg",
            20,
            "veryfast",
            False,
        )


def test_rejects_tampered_cohort_video(tmp_path):
    cohort = _cohort(tmp_path)
    (cohort / "videos/validation/upfall_s09.mp4").write_bytes(b"tampered")

    with pytest.raises(review.ReviewPackageError, match="SHA-256"):
        review.load_cohort(cohort)


def test_rejects_empty_false_event_analysis(tmp_path):
    root = tmp_path / "analysis"
    root.mkdir()
    csv_content = (
        "review_id,source_dataset,video_id,event_frame,event_sec,"
        "review_start_sec,review_end_sec,active_labels,confirm_path,"
        "candidate_entry_reason,diagnostic_route\n"
    )
    (root / "false_events.csv").write_text(csv_content, encoding="utf-8")
    (root / "false_event_analysis.json").write_text(
        json.dumps(
            {
                "schema_version": "real_rgb_false_event_analysis_v1",
                "false_events_csv_sha256": hashlib.sha256(
                    csv_content.encode()
                ).hexdigest(),
                "summary": {"false_event_count": 0},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(review.ReviewPackageError, match="false Event"):
        review.load_analysis(root)
