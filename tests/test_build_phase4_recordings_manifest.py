from __future__ import annotations

import csv
import shutil
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import build_phase4_recordings_manifest as build_manifest  # noqa: E402
import phase4_recording_contract as contract  # noqa: E402


def _write_video(path: Path, frame_count: int = 4) -> None:
    writer = cv2.VideoWriter(
        str(path),
        cv2.VideoWriter_fourcc(*"mp4v"),
        20.0,
        (32, 24),
    )
    assert writer.isOpened()
    file_offset = sum(path.name.encode("utf-8")) % 120
    for index in range(frame_count):
        writer.write(
            np.full((24, 32, 3), file_offset + index * 20, dtype=np.uint8)
        )
    writer.release()


def _review_row(filename: str, *, actors: str, label: str) -> dict[str, str]:
    parsed = contract.parse_recording_name(filename)
    return {
        "review_index": "001",
        "original_filename": f"original_{parsed.primary_actor_id}.mp4",
        "contract_filename": filename,
        "actor_ids": actors,
        "primary_actor_id": parsed.primary_actor_id,
        "scenario_type": parsed.scenario_type,
        "label": label,
        "visual_review_status": "human_confirmed",
        "notes": "",
    }


def _create_recording(
    root: Path,
    filename: str,
) -> tuple[Path, Path]:
    review = root / "data" / "datasets" / "phase4_recordings" / "a_fall_review"
    review.mkdir(parents=True, exist_ok=True)
    video = review / filename
    _write_video(video)
    return review, video


def _create_linked_recording(
    root: Path,
    filename: str,
    original_filename: str,
) -> tuple[Path, Path]:
    incoming = root / "data" / "datasets" / "phase4_recordings" / "incoming"
    review = root / "data" / "datasets" / "phase4_recordings" / "a_fall_review"
    incoming.mkdir(parents=True, exist_ok=True)
    review.mkdir(parents=True, exist_ok=True)
    original = incoming / original_filename
    _write_video(original)
    link = review / filename
    try:
        link.symlink_to(Path("../incoming") / original.name)
    except OSError as exc:
        pytest.skip(f"symlink 생성 권한이 없어 이 테스트를 건너뜁니다: {exc}")
    return review, link


def test_builds_actor_disjoint_manifest_and_verifies_video(tmp_path):
    a01_name = "P4_S01_A01_fall_backward_01_cam01.mp4"
    a03_name = "P4_S01_A03_pick_up_01_cam01.mp4"
    review_dir, _ = _create_recording(tmp_path, a01_name)
    _create_recording(tmp_path, a03_name)
    review_rows = [
        _review_row(a01_name, actors="A01", label="fall"),
        _review_row(a03_name, actors="A03", label="no_fall"),
    ]

    rows = build_manifest.build_manifest_rows(
        review_rows,
        recordings_dir=review_dir,
        repo_root=tmp_path,
        test_actors={"A03"},
        lighting="indoor",
        consent_status="confirmed",
        full_decode_check=True,
    )

    by_actor = {row["primary_actor_id"]: row for row in rows}
    assert by_actor["A01"]["split_role"] == "diagnostic"
    assert by_actor["A03"]["split_role"] == "test"
    assert by_actor["A01"]["frame_count"] == 4
    assert by_actor["A01"]["width"] == 32
    assert by_actor["A01"]["height"] == 24
    assert by_actor["A01"]["video_path"].endswith(a01_name)
    assert len(by_actor["A01"]["checksum_sha256"]) == 64
    contract.validate_recordings_manifest(rows)


def test_rejects_test_and_diagnostic_actor_in_same_video(tmp_path):
    filename = "P4_S01_A01_contact_fall_01_cam01.mp4"
    review_dir, _ = _create_recording(tmp_path, filename)
    row = _review_row(filename, actors="A01|A03", label="fall")

    with pytest.raises(ValueError, match="test actor"):
        build_manifest.build_manifest_rows(
            [row],
            recordings_dir=review_dir,
            repo_root=tmp_path,
            test_actors={"A03"},
            lighting="indoor",
            consent_status="confirmed",
            full_decode_check=False,
        )


def test_rejects_review_plan_original_mismatch(tmp_path):
    filename = "P4_S01_A01_fall_side_01_cam01.mp4"
    review_dir, _ = _create_linked_recording(tmp_path, filename, "actual.mp4")
    row = _review_row(filename, actors="A01", label="fall")

    with pytest.raises(ValueError, match="symlink 원본"):
        build_manifest.build_manifest_rows(
            [row],
            recordings_dir=review_dir,
            repo_root=tmp_path,
            test_actors=set(),
            lighting="indoor",
            consent_status="confirmed",
            full_decode_check=False,
        )


def test_rejects_duplicate_source_target(tmp_path):
    first = "P4_S01_A01_fall_side_01_cam01.mp4"
    second = "P4_S01_A01_fall_side_02_cam01.mp4"
    review_dir, first_video = _create_recording(tmp_path, first)
    second_video = review_dir / second
    shutil.copyfile(first_video, second_video)
    rows = [
        _review_row(first, actors="A01", label="fall"),
        {
            **_review_row(second, actors="A01", label="fall"),
            "original_filename": "original_A01.mp4",
        },
    ]

    with pytest.raises(ValueError, match="동일한 영상 내용"):
        build_manifest.build_manifest_rows(
            rows,
            recordings_dir=review_dir,
            repo_root=tmp_path,
            test_actors=set(),
            lighting="indoor",
            consent_status="confirmed",
            full_decode_check=False,
        )


def test_load_review_plan_requires_exact_header(tmp_path):
    path = tmp_path / "review.csv"
    path.write_text("contract_filename,label\nx.mp4,fall\n", encoding="utf-8")

    with pytest.raises(ValueError, match="header"):
        build_manifest.load_review_plan(path)


def test_load_review_plan_reads_expected_contract(tmp_path):
    filename = "P4_S01_A01_fall_side_01_cam01.mp4"
    row = _review_row(filename, actors="A01", label="fall")
    path = tmp_path / "review.csv"
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=build_manifest.REVIEW_PLAN_FIELDS)
        writer.writeheader()
        writer.writerow(row)

    assert build_manifest.load_review_plan(path) == [row]
