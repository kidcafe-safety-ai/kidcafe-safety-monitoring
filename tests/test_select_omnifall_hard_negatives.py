"""OmniFall E1 hard-negative cohort 선별 도구 테스트."""

from __future__ import annotations

import csv
import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import select_omnifall_hard_negatives as selector  # noqa: E402


LABEL_FIELDS = [
    "path",
    "label",
    "start",
    "end",
    "age_group",
    "environment_category",
    "gender_presentation",
    "camera_elevation",
    "camera_distance",
]


def _row(
    path: str,
    label: int,
    start: float = 0.0,
    end: float = 2.0,
    age: str = "adults_18_64",
    environment: str = "indoor",
) -> dict:
    return {
        "path": path,
        "label": str(label),
        "start": str(start),
        "end": str(end),
        "age_group": age,
        "environment_category": environment,
        "gender_presentation": "female",
        "camera_elevation": "eye",
        "camera_distance": "medium",
    }


def _write_csv(path: Path, fieldnames: list, rows: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _inputs(tmp_path: Path, rows: list, train_paths: list) -> tuple:
    labels = tmp_path / "of-syn.csv"
    split = tmp_path / "train.csv"
    _write_csv(labels, LABEL_FIELDS, rows)
    _write_csv(split, ["path"], [{"path": path} for path in train_paths])
    return labels, split


def test_audit_excludes_non_train_positive_mixed_and_zero_duration(tmp_path):
    rows = [
        _row("sit_down/pure", 3),
        _row("sit_down/mixed", 3),
        _row("sit_down/mixed", 1, 2.0, 3.0),
        _row("sit_down/zero", 3, 5.0, 5.0),
        _row("sit_down/not_train", 3),
    ]
    labels, split = _inputs(
        tmp_path,
        rows,
        ["sit_down/pure", "sit_down/mixed", "sit_down/zero"],
    )

    candidates, audit = selector.audit_candidates(labels, split)

    assert [segment.path for segment in candidates] == ["sit_down/pure"]
    assert audit.total_label_rows == 5
    assert audit.split_video_count == 3
    assert audit.positive_video_count == 1
    assert audit.target_segment_count == 2
    assert audit.excluded_positive_target_segment_count == 1
    assert audit.eligible_target_segment_count == 1
    assert audit.deduplicated_candidate_count == 1
    assert len(audit.zero_duration_rows) == 1
    assert audit.zero_duration_rows[0]["path"] == "sit_down/zero"


def test_zero_duration_fall_still_excludes_entire_video(tmp_path):
    rows = [
        _row("kneeling/mixed", 11, 0.0, 2.0),
        _row("kneeling/mixed", 1, 5.0, 5.0),
        _row("kneeling/pure", 11, 0.0, 2.0),
    ]
    labels, split = _inputs(
        tmp_path, rows, ["kneeling/mixed", "kneeling/pure"]
    )

    candidates, _ = selector.audit_candidates(labels, split)

    assert [segment.path for segment in candidates] == ["kneeling/pure"]


@pytest.mark.parametrize("primary_category", ["fall", "fallen"])
def test_positive_primary_category_is_excluded_without_positive_label(
    tmp_path, primary_category
):
    rows = [
        _row(f"{primary_category}/annotation_anomaly", 3),
        _row("sit_down/pure", 3),
    ]
    paths = [row["path"] for row in rows]
    labels, split = _inputs(tmp_path, rows, paths)

    candidates, audit = selector.audit_candidates(labels, split)

    assert [segment.path for segment in candidates] == ["sit_down/pure"]
    assert audit.excluded_positive_primary_target_segment_count == 1


def test_longest_segment_is_kept_per_video_and_activity(tmp_path):
    rows = [
        _row("sitting/a", 4, 0.0, 1.0),
        _row("sitting/a", 4, 1.0, 4.0),
    ]
    labels, split = _inputs(tmp_path, rows, ["sitting/a"])

    candidates, _ = selector.audit_candidates(labels, split)

    assert len(candidates) == 1
    assert candidates[0].start_sec == 1.0
    assert candidates[0].end_sec == 4.0


def test_negative_duration_fails_closed(tmp_path):
    rows = [_row("crawl/a", 14, 2.0, 1.0)]
    labels, split = _inputs(tmp_path, rows, ["crawl/a"])

    with pytest.raises(selector.SelectionError, match="역전"):
        selector.audit_candidates(labels, split)


def test_duplicate_train_path_is_rejected(tmp_path):
    rows = [_row("crawl/a", 14)]
    labels, split = _inputs(tmp_path, rows, ["crawl/a", "crawl/a"])

    with pytest.raises(selector.SelectionError, match="중복"):
        selector.audit_candidates(labels, split)


def test_balancing_round_robins_age_and_environment_strata():
    candidates = []
    for index in range(4):
        candidates.append(
            selector.Segment(
                path=f"sitting/adult_{index}",
                label=4,
                activity="sitting",
                start_sec=0.0,
                end_sec=2.0,
                duration_sec=2.0,
                age_group="adults_18_64",
                environment_category="indoor",
                gender_presentation="female",
                camera_elevation="eye",
                camera_distance="medium",
            )
        )
    candidates.append(
        selector.Segment(
            path="sitting/child",
            label=4,
            activity="sitting",
            start_sec=0.0,
            end_sec=2.0,
            duration_sec=2.0,
            age_group="children_5_12",
            environment_category="outdoor",
            gender_presentation="male",
            camera_elevation="high",
            camera_distance="far",
        )
    )

    selected = selector.select_balanced(candidates, max_per_activity=2, seed=42)

    assert {segment.age_group for segment in selected} == {
        "adults_18_64",
        "children_5_12",
    }


def test_selection_is_deterministic():
    candidates = [
        selector.Segment(
            path=f"crawl/{index}",
            label=14,
            activity="crawl",
            start_sec=0.0,
            end_sec=2.0,
            duration_sec=2.0,
            age_group="children_5_12",
            environment_category="indoor",
            gender_presentation="female",
            camera_elevation="eye",
            camera_distance="medium",
        )
        for index in range(10)
    ]

    first = selector.select_balanced(candidates, max_per_activity=4, seed=7)
    second = selector.select_balanced(reversed(candidates), max_per_activity=4, seed=7)

    assert [item.path for item in first] == [item.path for item in second]


def test_write_selection_records_source_and_policy(tmp_path):
    rows = [
        _row("sit_down/a", 3),
        _row("crawl/b", 14, age="children_5_12", environment="outdoor"),
    ]
    labels, split = _inputs(tmp_path, rows, ["sit_down/a", "crawl/b"])
    source_manifest = tmp_path / "source.json"
    source_manifest.write_text(
        json.dumps(
            {
                "repository": "simplexsigil2/omnifall",
                "revision": "abc123",
                "archive_sha256": "f" * 64,
            }
        ),
        encoding="utf-8",
    )
    candidates, audit = selector.audit_candidates(labels, split)
    selected = selector.select_balanced(candidates, max_per_activity=100, seed=42)
    output = tmp_path / "output"

    selector.write_selection(
        labels_path=labels,
        split_path=split,
        split_role="validation",
        source_manifest_path=source_manifest,
        output_dir=output,
        selected=selected,
        audit=audit,
        max_per_activity=100,
        seed=42,
        force=False,
    )

    manifest = json.loads((output / selector.OUTPUT_JSON).read_text())
    selection_rows = list(
        csv.DictReader((output / selector.OUTPUT_CSV).open(encoding="utf-8"))
    )
    assert manifest["schema_version"] == selector.SELECTION_SCHEMA_VERSION
    assert manifest["source"]["repository_revision"] == "abc123"
    assert manifest["source"]["split_path"] == str(split)
    assert manifest["source"]["split_sha256"] == selector._sha256(split)
    assert manifest["policy"]["split_family"] == "of-syn random"
    assert manifest["policy"]["split_role"] == "validation"
    assert "not training input" in manifest["policy"]["purpose"]
    assert manifest["policy"]["max_segments_per_activity"] == 100
    assert manifest["selection"]["segment_count"] == 2
    assert len(selection_rows) == 2
    assert manifest["selection"]["csv_sha256"] == hashlib.sha256(
        (output / selector.OUTPUT_CSV).read_bytes()
    ).hexdigest()
    assert {row["archive_member"] for row in selection_rows} == {
        "sit_down/a.mp4",
        "crawl/b.mp4",
    }


def test_existing_output_requires_force(tmp_path):
    rows = [_row("crawl/a", 14)]
    labels, split = _inputs(tmp_path, rows, ["crawl/a"])
    candidates, audit = selector.audit_candidates(labels, split)
    output = tmp_path / "output"
    output.mkdir()
    (output / selector.OUTPUT_CSV).write_text("existing", encoding="utf-8")

    with pytest.raises(selector.SelectionError, match="force"):
        selector.write_selection(
            labels_path=labels,
            split_path=split,
            split_role="train",
            source_manifest_path=None,
            output_dir=output,
            selected=candidates,
            audit=audit,
            max_per_activity=100,
            seed=42,
            force=False,
        )


def test_source_manifest_requires_valid_revision_and_sha256(tmp_path):
    rows = [_row("crawl/a", 14)]
    labels, split = _inputs(tmp_path, rows, ["crawl/a"])
    candidates, audit = selector.audit_candidates(labels, split)
    source_manifest = tmp_path / "source.json"
    source_manifest.write_text(
        json.dumps(
            {
                "repository": "simplexsigil2/omnifall",
                "revision": "abc123",
                "archive_sha256": "INVALID",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(selector.SelectionError, match="SHA-256"):
        selector.write_selection(
            labels_path=labels,
            split_path=split,
            split_role="train",
            source_manifest_path=source_manifest,
            output_dir=tmp_path / "output",
            selected=candidates,
            audit=audit,
            max_per_activity=100,
            seed=42,
            force=False,
        )


def test_write_selection_rejects_unknown_split_role(tmp_path):
    rows = [_row("crawl/a", 14)]
    labels, split = _inputs(tmp_path, rows, ["crawl/a"])
    candidates, audit = selector.audit_candidates(labels, split)

    with pytest.raises(selector.SelectionError, match="split_role"):
        selector.write_selection(
            labels_path=labels,
            split_path=split,
            split_role="development",
            source_manifest_path=None,
            output_dir=tmp_path / "output",
            selected=candidates,
            audit=audit,
            max_per_activity=100,
            seed=42,
            force=False,
        )
