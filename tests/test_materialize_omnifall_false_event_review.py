"""OmniFall false Event 검수 clip materializer 테스트."""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import materialize_omnifall_false_event_review as materializer  # noqa: E402


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _inputs(tmp_path: Path) -> tuple[Path, Path]:
    analysis = tmp_path / "analysis"
    analysis.mkdir()
    csv_path = analysis / materializer.ANALYSIS_CSV
    fields = [
        "review_id",
        "video_id",
        "event_frame",
        "event_sec",
        "review_start_sec",
        "review_end_sec",
        "confirm_path",
        "candidate_entry_reason",
        "active_labels",
        "diagnostic_route",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerow(
            {
                "review_id": "ofsyn_lie_down_a_event_01",
                "video_id": "ofsyn_lie_down_a",
                "event_frame": 40,
                "event_sec": 2.0,
                "review_start_sec": 1.0,
                "review_end_sec": 3.0,
                "confirm_path": "bbox",
                "candidate_entry_reason": "dynamic",
                "active_labels": "lie_down",
                "diagnostic_route": "rule_or_temporal",
            }
        )
    (analysis / materializer.ANALYSIS_JSON).write_text(
        json.dumps(
            {
                "schema_version": materializer.ANALYSIS_SCHEMA_VERSION,
                "false_events_csv_sha256": _sha256(csv_path),
                "summary": {"false_event_count": 1},
            }
        ),
        encoding="utf-8",
    )

    cohort = tmp_path / "cohort"
    video = cohort / "videos/lie_down/a.mp4"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"h264-source")
    (cohort / materializer.TRANSCODE_MANIFEST).write_text(
        json.dumps(
            {
                "schema_version": materializer.TRANSCODE_SCHEMA_VERSION,
                "video_count": 1,
                "videos": [
                    {
                        "video_id": "ofsyn_lie_down_a",
                        "video_path": "videos/lie_down/a.mp4",
                        "output_sha256": _sha256(video),
                        "output_probe": {"duration_sec": 5.0},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return analysis, cohort


def _fake_ffmpeg(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda value: f"/usr/bin/{value}")

    def fake_clip(source, destination, start, duration, ffmpeg, crf, preset):
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"review-clip")

    monkeypatch.setattr(materializer, "_run_clip", fake_clip)


def test_materializes_review_clip_csv_and_provenance(tmp_path, monkeypatch):
    analysis, cohort = _inputs(tmp_path)
    output = tmp_path / "review"
    _fake_ffmpeg(monkeypatch)

    manifest = materializer.materialize_review(
        analysis, cohort, output, "ffmpeg", 20, "veryfast", False
    )

    clip = output / "clips/ofsyn_lie_down_a_event_01.mp4"
    rows = list(
        csv.DictReader((output / materializer.REVIEW_CSV).open(encoding="utf-8"))
    )
    assert manifest["schema_version"] == materializer.REVIEW_SCHEMA_VERSION
    assert manifest["clip_count"] == 1
    assert clip.read_bytes() == b"review-clip"
    assert rows[0]["event_offset_sec"] == "1.0"
    assert rows[0]["review_status"] == "pending"
    assert rows[0]["review_decision"] == ""
    assert rows[0]["selected_for_training"] == "false"
    assert manifest["review_csv_sha256"] == _sha256(
        output / materializer.REVIEW_CSV
    )
    assert manifest["clips"][0]["clip_sha256"] == _sha256(clip)


def test_rejects_tampered_analysis_csv(tmp_path, monkeypatch):
    analysis, cohort = _inputs(tmp_path)
    with (analysis / materializer.ANALYSIS_CSV).open("a", encoding="utf-8") as file:
        file.write("tampered")
    _fake_ffmpeg(monkeypatch)

    with pytest.raises(materializer.ReviewPackageError, match="SHA-256"):
        materializer.materialize_review(
            analysis, cohort, tmp_path / "out", "ffmpeg", 20, "veryfast", False
        )


def test_rejects_analysis_summary_count_mismatch(tmp_path):
    analysis, _ = _inputs(tmp_path)
    manifest_path = analysis / materializer.ANALYSIS_JSON
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["summary"]["false_event_count"] = 2
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(materializer.ReviewPackageError, match="CSV 행 수"):
        materializer.load_analysis(analysis)


def test_rejects_tampered_source_video(tmp_path, monkeypatch):
    analysis, cohort = _inputs(tmp_path)
    (cohort / "videos/lie_down/a.mp4").write_bytes(b"tampered")
    _fake_ffmpeg(monkeypatch)

    with pytest.raises(materializer.ReviewPackageError, match="SHA-256"):
        materializer.materialize_review(
            analysis, cohort, tmp_path / "out", "ffmpeg", 20, "veryfast", False
        )


def test_rejects_non_positive_video_duration(tmp_path):
    _, cohort = _inputs(tmp_path)
    manifest_path = cohort / materializer.TRANSCODE_MANIFEST
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["videos"][0]["output_probe"]["duration_sec"] = 0.0
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(materializer.ReviewPackageError, match="duration"):
        materializer.load_cohort(cohort)


@pytest.mark.parametrize(
    "review_id",
    ["../escape", "bad/id", "", "event id"],
)
def test_rejects_unsafe_review_id(tmp_path, review_id):
    analysis, _ = _inputs(tmp_path)
    csv_path = analysis / materializer.ANALYSIS_CSV
    rows = list(csv.DictReader(csv_path.open(encoding="utf-8")))
    rows[0]["review_id"] = review_id
    with csv_path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=rows[0], lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    manifest_path = analysis / materializer.ANALYSIS_JSON
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["false_events_csv_sha256"] = _sha256(csv_path)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(materializer.ReviewPackageError, match="review_id"):
        materializer.load_analysis(analysis)


def test_existing_output_requires_force(tmp_path, monkeypatch):
    analysis, cohort = _inputs(tmp_path)
    output = tmp_path / "review"
    output.mkdir()
    marker = output / "old.txt"
    marker.write_text("old", encoding="utf-8")
    _fake_ffmpeg(monkeypatch)

    with pytest.raises(materializer.ReviewPackageError, match="force"):
        materializer.materialize_review(
            analysis, cohort, output, "ffmpeg", 20, "veryfast", False
        )

    assert marker.read_text(encoding="utf-8") == "old"


def test_failed_clip_keeps_existing_output(tmp_path, monkeypatch):
    analysis, cohort = _inputs(tmp_path)
    output = tmp_path / "review"
    output.mkdir()
    marker = output / "old.txt"
    marker.write_text("old", encoding="utf-8")
    monkeypatch.setattr(shutil, "which", lambda value: f"/usr/bin/{value}")

    def fail(*args, **kwargs):
        raise materializer.ReviewPackageError("failed")

    monkeypatch.setattr(materializer, "_run_clip", fail)

    with pytest.raises(materializer.ReviewPackageError, match="failed"):
        materializer.materialize_review(
            analysis, cohort, output, "ffmpeg", 20, "veryfast", True
        )

    assert marker.read_text(encoding="utf-8") == "old"
