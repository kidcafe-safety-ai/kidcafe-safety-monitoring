"""OmniFall 선별 cohort materializer 테스트."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import sys
import tarfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import materialize_omnifall_cohort as materializer  # noqa: E402
from evaluate_fall import load_annotations, validate_annotations  # noqa: E402


FIELDS = [
    "selection_id",
    "path",
    "archive_member",
    "label",
    "activity",
    "start_sec",
    "end_sec",
    "duration_sec",
]


def _selection(tmp_path: Path, rows: list, archive_sha256: str) -> Path:
    directory = tmp_path / "selection"
    directory.mkdir()
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    csv_content = output.getvalue()
    (directory / materializer.SELECTION_CSV).write_text(
        csv_content, encoding="utf-8"
    )
    manifest = {
        "schema_version": materializer.SELECTION_SCHEMA_VERSION,
        "source": {"archive_sha256": archive_sha256},
        "selection": {
            "segment_count": len(rows),
            "csv_sha256": hashlib.sha256(csv_content.encode()).hexdigest(),
        },
    }
    (directory / materializer.SELECTION_JSON).write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    return directory


def _archive(tmp_path: Path, files: dict) -> Path:
    path = tmp_path / "videos.tar"
    with tarfile.open(path, "w") as archive:
        for name, content in files.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))
    return path


def _row(selection_id: str, path: str, activity: str) -> dict:
    return {
        "selection_id": selection_id,
        "path": path,
        "archive_member": f"{path}.mp4",
        "label": "3",
        "activity": activity,
        "start_sec": "0.0",
        "end_sec": "2.0",
        "duration_sec": "2.0",
    }


def test_materializes_unique_videos_and_writes_annotations(tmp_path):
    archive = _archive(
        tmp_path,
        {
            "sit_down/a.mp4": b"video-a",
            "crawl/b.mp4": b"video-b",
        },
    )
    rows = [
        _row("sit_1", "sit_down/a", "sit_down"),
        _row("sit_2", "sit_down/a", "sitting"),
        _row("crawl_1", "crawl/b", "crawl"),
    ]
    selection = _selection(tmp_path, rows, materializer._sha256(archive))
    output = tmp_path / "cohort"

    manifest = materializer.materialize(archive, selection, output, force=False)

    assert manifest["segment_count"] == 3
    assert manifest["video_count"] == 2
    assert (output / "videos/sit_down/a.mp4").read_bytes() == b"video-a"
    annotations = list(
        csv.DictReader(
            (output / materializer.ANNOTATIONS_CSV).open(encoding="utf-8")
        )
    )
    assert len(annotations) == 2
    assert {row["label"] for row in annotations} == {"no_fall"}
    assert {row["review_status"] for row in annotations} == {"reviewed"}
    assert all(row["video_path"].startswith("videos/") for row in annotations)
    loaded = load_annotations(
        str(output / materializer.ANNOTATIONS_CSV), include_unreviewed=False
    )
    validate_annotations(loaded)
    assert len(loaded) == 2


def test_rejects_selection_csv_checksum_mismatch(tmp_path):
    archive = _archive(tmp_path, {"crawl/a.mp4": b"video"})
    selection = _selection(
        tmp_path,
        [_row("crawl_1", "crawl/a", "crawl")],
        materializer._sha256(archive),
    )
    with (selection / materializer.SELECTION_CSV).open("a", encoding="utf-8") as file:
        file.write("tampered")

    with pytest.raises(materializer.MaterializationError, match="SHA-256"):
        materializer.materialize(archive, selection, tmp_path / "out", False)


def test_rejects_archive_checksum_mismatch(tmp_path):
    archive = _archive(tmp_path, {"crawl/a.mp4": b"video"})
    selection = _selection(
        tmp_path, [_row("crawl_1", "crawl/a", "crawl")], "f" * 64
    )

    with pytest.raises(materializer.MaterializationError, match="archive SHA-256"):
        materializer.materialize(archive, selection, tmp_path / "out", False)


@pytest.mark.parametrize(
    "member",
    ["../escape.mp4", "/absolute.mp4", "crawl/a.avi", "wrong/a.mp4"],
)
def test_rejects_unsafe_or_mismatched_member(tmp_path, member):
    row = _row("crawl_1", "crawl/a", "crawl")
    row["archive_member"] = member

    with pytest.raises(materializer.MaterializationError):
        materializer.validate_rows([row])


def test_missing_archive_member_fails_before_partial_extraction(tmp_path):
    archive = _archive(tmp_path, {"crawl/a.mp4": b"video"})
    rows = [
        _row("crawl_1", "crawl/a", "crawl"),
        _row("crawl_2", "crawl/missing", "crawl"),
    ]
    selection = _selection(tmp_path, rows, materializer._sha256(archive))
    output = tmp_path / "out"

    with pytest.raises(materializer.MaterializationError, match="없습니다"):
        materializer.materialize(archive, selection, output, False)

    assert list((output / "videos").rglob("*.mp4")) == []


def test_existing_output_requires_force(tmp_path):
    archive = _archive(tmp_path, {"crawl/a.mp4": b"video"})
    selection = _selection(
        tmp_path,
        [_row("crawl_1", "crawl/a", "crawl")],
        materializer._sha256(archive),
    )
    output = tmp_path / "out"
    materializer.materialize(archive, selection, output, False)

    with pytest.raises(materializer.MaterializationError, match="force"):
        materializer.materialize(archive, selection, output, False)

    manifest = materializer.materialize(archive, selection, output, True)
    assert manifest["video_count"] == 1
