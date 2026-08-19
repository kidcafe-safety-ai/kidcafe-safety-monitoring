from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import generate_phase4_zone_intervals as generate_intervals  # noqa: E402
import phase4_recording_contract as contract  # noqa: E402


def _manifest_row(**overrides) -> dict[str, str]:
    row = {
        "video_id": "P4_S01_A01_zone_enter_exit_01_cam01",
        "session_id": "S01",
        "actor_ids": "A01",
        "primary_actor_id": "A01",
        "camera_id": "cam01",
        "scenario_type": "zone_enter_exit",
        "label": "no_fall",
        "video_path": "data/P4_S01_A01_zone_enter_exit_01_cam01.mp4",
        "fps": "60",
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


def test_seeds_one_pending_interval_per_video():
    rows = generate_intervals.build_interval_rows([_manifest_row()], zone_id="play_floor")

    assert rows[0]["video_id"] == "P4_S01_A01_zone_enter_exit_01_cam01"
    assert rows[0]["zone_id"] == "play_floor"
    assert rows[0]["interval_index"] == "1"
    assert rows[0]["enter_frame"] == ""
    assert rows[0]["exit_frame"] == ""
    assert rows[0]["review_status"] == "pending"
    contract.validate_zone_intervals(rows, [_manifest_row()])


def test_preserves_manifest_order():
    first = _manifest_row()
    second = _manifest_row(
        video_id="P4_S01_A02_zone_enter_exit_01_cam01",
        actor_ids="A02",
        primary_actor_id="A02",
        video_path="data/P4_S01_A02_zone_enter_exit_01_cam01.mp4",
        checksum_sha256="b" * 64,
    )

    rows = generate_intervals.build_interval_rows([first, second], zone_id="play_floor")

    assert [row["video_id"] for row in rows] == [first["video_id"], second["video_id"]]


def test_rejects_blank_zone_id():
    with pytest.raises(ValueError, match="zone_id"):
        generate_intervals.build_interval_rows([_manifest_row()], zone_id="  ")
