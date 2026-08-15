from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import generate_phase4_fall_annotations as generate_annotations  # noqa: E402
import phase4_recording_contract as contract  # noqa: E402


def _manifest_row(**overrides) -> dict[str, str]:
    row = {
        "video_id": "P4_S01_A01_fall_backward_01_cam01",
        "session_id": "S01",
        "actor_ids": "A01",
        "primary_actor_id": "A01",
        "camera_id": "cam01",
        "scenario_type": "fall_backward",
        "label": "fall",
        "video_path": "data/P4_S01_A01_fall_backward_01_cam01.mp4",
        "fps": "30",
        "frame_count": "300",
        "width": "1920",
        "height": "1080",
        "lighting": "indoor",
        "split_role": "diagnostic",
        "review_status": "reviewed",
        "consent_status": "confirmed",
        "checksum_sha256": "a" * 64,
    }
    row.update(overrides)
    return row


def test_seeds_single_actor_fall_as_cause_null_pending():
    rows = generate_annotations.build_annotation_rows([_manifest_row()])

    assert rows[0]["victim_actor_id"] == "A01"
    assert rows[0]["contact_occurred"] == "false"
    assert rows[0]["cause_candidate_exists"] == "false"
    assert rows[0]["cause_actor_id"] == ""
    assert rows[0]["review_status"] == "pending"
    contract.validate_fall_cause_annotations(rows, [_manifest_row()])


def test_seeds_contact_fall_actor_candidate_without_marking_reviewed():
    manifest = _manifest_row(
        video_id="P4_S01_A01_contact_fall_01_cam01",
        actor_ids="A01|A02",
        scenario_type="contact_fall",
        video_path="data/P4_S01_A01_contact_fall_01_cam01.mp4",
    )

    row = generate_annotations.build_annotation_rows([manifest])[0]

    assert row["victim_actor_id"] == "A01"
    assert row["contact_occurred"] == "true"
    assert row["cause_candidate_exists"] == "true"
    assert row["cause_actor_id"] == "A02"
    assert row["contact_frame"] == ""
    assert row["review_status"] == "pending"
    contract.validate_fall_cause_annotations([row], [manifest])


def test_no_fall_has_no_victim_or_cause():
    manifest = _manifest_row(
        video_id="P4_S01_A01_near_pass_01_cam01",
        actor_ids="A01|A02",
        scenario_type="near_pass",
        label="no_fall",
        video_path="data/P4_S01_A01_near_pass_01_cam01.mp4",
    )

    row = generate_annotations.build_annotation_rows([manifest])[0]

    assert row["victim_actor_id"] == ""
    assert row["contact_occurred"] == "false"
    assert row["cause_candidate_exists"] == "false"
    assert row["cause_actor_id"] == ""
    contract.validate_fall_cause_annotations([row], [manifest])


def test_preserves_manifest_order():
    first = _manifest_row()
    second = _manifest_row(
        video_id="P4_S01_A02_pick_up_01_cam01",
        actor_ids="A02",
        primary_actor_id="A02",
        scenario_type="pick_up",
        label="no_fall",
        video_path="data/P4_S01_A02_pick_up_01_cam01.mp4",
        checksum_sha256="b" * 64,
    )

    rows = generate_annotations.build_annotation_rows([first, second])

    assert [row["video_id"] for row in rows] == [first["video_id"], second["video_id"]]
