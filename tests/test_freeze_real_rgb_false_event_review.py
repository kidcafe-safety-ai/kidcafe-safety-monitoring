import csv
import json
from pathlib import Path

import pytest

from scripts.freeze_real_rgb_false_event_review import (
    FROZEN_CSV,
    FROZEN_MANIFEST,
    FreezeReviewError,
    freeze_review,
)
from scripts.materialize_real_rgb_false_event_review import (
    REVIEW_MANIFEST,
    REVIEW_SCHEMA_VERSION,
)
from scripts.real_rgb_cohort import sha256_file


FIELDS = [
    "review_id",
    "source_dataset",
    "video_id",
    "review_status",
    "review_decision",
    "selected_for_training",
    "reviewer_id",
]


def _write_csv(path: Path, rows: list[dict]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _package(tmp_path: Path) -> tuple[Path, Path]:
    review_dir = tmp_path / "review"
    clips_dir = review_dir / "clips"
    clips_dir.mkdir(parents=True)
    clip = clips_dir / "r1.mp4"
    clip.write_bytes(b"video")
    manifest = {
        "schema_version": REVIEW_SCHEMA_VERSION,
        "source_dataset": "up_fall",
        "clip_count": 1,
        "clips": [
            {
                "review_id": "r1",
                "video_id": "v1",
                "clip_path": "clips/r1.mp4",
                "clip_sha256": sha256_file(clip),
            }
        ],
    }
    (review_dir / REVIEW_MANIFEST).write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    completed = tmp_path / "completed.csv"
    _write_csv(
        completed,
        [
            {
                "review_id": "r1",
                "source_dataset": "up_fall",
                "video_id": "v1",
                "review_status": "reviewed",
                "review_decision": "hard_negative",
                "selected_for_training": "true",
                "reviewer_id": "reviewer-a",
            }
        ],
    )
    return review_dir, completed


def test_freeze_review_writes_validated_copy_and_manifest(tmp_path):
    review_dir, completed = _package(tmp_path)
    output = tmp_path / "frozen"

    result = freeze_review(review_dir, completed, output, False)

    assert result["review_count"] == 1
    assert result["selected_for_training_count"] == 1
    assert result["selected_video_count"] == 1
    assert result["frozen_review_csv_sha256"] == sha256_file(output / FROZEN_CSV)
    assert json.loads((output / FROZEN_MANIFEST).read_text(encoding="utf-8")) == result


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("review_status", "pending", "reviewed/needs_review"),
        ("review_decision", "label_error", "학습 선택"),
        ("reviewer_id", "", "reviewer_id"),
        ("selected_for_training", "yes", "true/false"),
    ],
)
def test_freeze_review_rejects_invalid_completed_rows(
    tmp_path, field, value, message
):
    review_dir, completed = _package(tmp_path)
    with open(completed, "r", encoding="utf-8", newline="") as file:
        row = next(csv.DictReader(file))
    row[field] = value
    _write_csv(completed, [row])

    with pytest.raises(FreezeReviewError, match=message):
        freeze_review(review_dir, completed, tmp_path / "frozen", False)


def test_freeze_review_rejects_changed_clip(tmp_path):
    review_dir, completed = _package(tmp_path)
    (review_dir / "clips" / "r1.mp4").write_bytes(b"changed")

    with pytest.raises(FreezeReviewError, match="변경"):
        freeze_review(review_dir, completed, tmp_path / "frozen", False)


def test_freeze_review_rejects_validation_source_mismatch(tmp_path):
    review_dir, completed = _package(tmp_path)
    with open(completed, "r", encoding="utf-8", newline="") as file:
        row = next(csv.DictReader(file))
    row["source_dataset"] = "gmdcsa24"
    _write_csv(completed, [row])

    with pytest.raises(FreezeReviewError, match="source_dataset"):
        freeze_review(review_dir, completed, tmp_path / "frozen", False)
