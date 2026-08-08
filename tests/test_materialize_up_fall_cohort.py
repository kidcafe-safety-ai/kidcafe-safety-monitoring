"""UP-Fall 실제 RGB cohort 생성 도구 테스트."""

from __future__ import annotations

import csv
import hashlib
import json
import struct
import sys
from pathlib import Path
from zipfile import ZipFile

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import materialize_up_fall_cohort as up_fall  # noqa: E402


def _png(width: int = 640, height: int = 480) -> bytes:
    return (
        up_fall.PNG_SIGNATURE
        + struct.pack(">I", 13)
        + b"IHDR"
        + struct.pack(">II", width, height)
        + b"\x08\x02\x00\x00\x00"
        + b"fake-crc"
    )


def _write_archive(path: Path, *, unsafe_name: str | None = None) -> None:
    with ZipFile(path, "w") as archive:
        first = unsafe_name or "2018-07-04T12_17_20.000000.png"
        archive.writestr(first, _png())
        archive.writestr("2018-07-04T12_17_20.055556.png", _png())


def _write_selection(
    root: Path,
    rows: list[dict] | None = None,
) -> tuple[Path, Path]:
    if rows is None:
        rows = [
            {
                "subject_id": 1,
                "activity_id": 8,
                "activity_name": "sitting",
                "trial_id": 1,
                "camera_id": 1,
                "split_role": "train_candidate",
            },
            {
                "subject_id": 9,
                "activity_id": 8,
                "activity_name": "sitting",
                "trial_id": 1,
                "camera_id": 1,
                "split_role": "validation_candidate",
            },
        ]
    fields = [
        "subject_id",
        "activity_id",
        "activity_name",
        "trial_id",
        "camera_id",
        "drive_file_id",
        "expected_bytes",
        "split_role",
        "download_url",
    ]
    checksum_lines = []
    materialized_rows = []
    for row in rows:
        filename = (
            f"Subject{row['subject_id']}Activity{row['activity_id']}"
            f"Trial{row['trial_id']}Camera{row['camera_id']}.zip"
        )
        archive_path = root / filename
        _write_archive(archive_path)
        digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
        checksum_lines.append(f"{digest}  {archive_path}\n")
        materialized_rows.append(
            {
                **row,
                "drive_file_id": f"drive-{filename}",
                "expected_bytes": archive_path.stat().st_size,
                "download_url": "https://example.invalid/download",
            }
        )
    selection = root / "selection.tsv"
    with open(selection, "w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields, delimiter="\t")
        writer.writeheader()
        writer.writerows(materialized_rows)
    checksums = root / "SHA256SUMS"
    checksums.write_text("".join(checksum_lines), encoding="utf-8")
    return selection, checksums


def _fake_video_tools(monkeypatch) -> None:
    monkeypatch.setattr(up_fall, "require_tools", lambda *args: None)

    def fake_transcode(source, destination, ffmpeg, fps, crf, preset):
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"h264")
        return {
            "frame_count": 2,
            "first_timestamp": "2018-07-04T12:17:20.000000",
            "last_timestamp": "2018-07-04T12:17:20.055556",
            "observed_fps": 17.999856,
        }

    monkeypatch.setattr(up_fall, "transcode_archive", fake_transcode)
    monkeypatch.setattr(
        up_fall,
        "probe_video",
        lambda path, ffprobe: {
            "codec_name": "h264",
            "width": 640,
            "height": 480,
            "fps": 18.0,
            "duration_sec": 2 / 18,
            "frame_count": 2,
        },
    )


def test_materializes_subject_disjoint_cohort(tmp_path, monkeypatch):
    selection, checksums = _write_selection(tmp_path)
    output = tmp_path / "output"
    _fake_video_tools(monkeypatch)

    manifest = up_fall.materialize(
        tmp_path,
        selection,
        checksums,
        output,
        "ffmpeg",
        "ffprobe",
        18.0,
        20,
        "veryfast",
        False,
    )

    assert manifest["schema_version"] == "real_rgb_fall_cohort_v1"
    assert manifest["split_counts"] == {"train_candidate": 1, "validation": 1}
    assert manifest["split_policy"]["train_candidate_subjects"] == [1]
    assert manifest["split_policy"]["validation_subjects"] == [9]
    assert (output / "annotations_train_candidate.csv").is_file()
    assert (output / "annotations_validation.csv").is_file()
    payload = json.loads((output / "cohort_manifest.json").read_text())
    assert payload["redistribution_allowed"] is False
    assert all(video["label"] == "no_fall" for video in payload["videos"])


def test_rejects_subject_in_two_splits(tmp_path):
    rows = [
        {
            "subject_id": 1,
            "activity_id": 8,
            "activity_name": "sitting",
            "trial_id": 1,
            "camera_id": 1,
            "split_role": "train_candidate",
        },
        {
            "subject_id": 1,
            "activity_id": 9,
            "activity_name": "picking_up_object",
            "trial_id": 1,
            "camera_id": 1,
            "split_role": "validation_candidate",
        },
    ]
    selection, checksums = _write_selection(tmp_path, rows)

    with pytest.raises(up_fall.CohortError, match="여러 split"):
        up_fall.load_selection(tmp_path, selection, checksums)


def test_rejects_archive_checksum_mismatch(tmp_path):
    selection, checksums = _write_selection(tmp_path)
    checksums.write_text("0" * 64 + "  Subject1Activity8Trial1Camera1.zip\n")

    with pytest.raises(up_fall.CohortError, match="SHA-256"):
        up_fall.load_selection(tmp_path, selection, checksums)


def test_validates_and_orders_timestamp_frames(tmp_path):
    archive_path = tmp_path / "frames.zip"
    with ZipFile(archive_path, "w") as archive:
        archive.writestr("2018-07-04T12_17_20.055556.png", _png())
        archive.writestr("2018-07-04T12_17_20.000000.png", _png())

    with ZipFile(archive_path) as archive:
        entries, timestamps = up_fall.validate_archive_entries(archive)

    assert [entry.filename for entry in entries] == [
        "2018-07-04T12_17_20.000000.png",
        "2018-07-04T12_17_20.055556.png",
    ]
    assert timestamps[0] < timestamps[1]


def test_rejects_unsafe_zip_member(tmp_path):
    archive_path = tmp_path / "unsafe.zip"
    _write_archive(archive_path, unsafe_name="../escape.png")

    with ZipFile(archive_path) as archive:
        with pytest.raises(up_fall.CohortError, match="안전하지"):
            up_fall.validate_archive_entries(archive)


def test_rejects_wrong_png_dimensions():
    with pytest.raises(up_fall.CohortError, match="해상도"):
        up_fall._validate_png_header(_png(width=320)[:24], "frame.png")


def test_existing_output_requires_force(tmp_path, monkeypatch):
    selection, checksums = _write_selection(tmp_path)
    output = tmp_path / "output"
    output.mkdir()
    _fake_video_tools(monkeypatch)

    with pytest.raises(up_fall.CohortError, match="force"):
        up_fall.materialize(
            tmp_path,
            selection,
            checksums,
            output,
            "ffmpeg",
            "ffprobe",
            18.0,
            20,
            "veryfast",
            False,
        )
