from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import derive_phase4_track_id_switches as derive_switches  # noqa: E402
import phase4_recording_contract as contract  # noqa: E402


def _segment_row(**overrides) -> dict[str, str]:
    row = {
        "run_id": "run_test",
        "video_id": "P4_S01_A01_contact_fall_01_cam01",
        "start_frame": "0",
        "end_frame": "99",
        "track_id": "1",
        "actor_id": "A01",
        "review_status": "reviewed",
        "notes": "",
    }
    row.update(overrides)
    return row


def _manifest_row(**overrides) -> dict[str, str]:
    row = {
        "video_id": "P4_S01_A01_contact_fall_01_cam01",
        "session_id": "S01",
        "actor_ids": "A01|A02",
        "primary_actor_id": "A01",
        "camera_id": "cam01",
        "scenario_type": "contact_fall",
        "label": "fall",
        "video_path": "data/P4_S01_A01_contact_fall_01_cam01.mp4",
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


def test_no_switch_for_single_contiguous_track():
    rows = [_segment_row()]

    switches = derive_switches.derive_switch_rows(rows)

    assert switches == []


def test_detects_switch_between_consecutive_segments_same_actor():
    rows = [
        _segment_row(track_id="1", start_frame="0", end_frame="99"),
        _segment_row(track_id="3", start_frame="100", end_frame="199"),
    ]

    switches = derive_switches.derive_switch_rows(rows)

    assert len(switches) == 1
    assert switches[0]["from_track_id"] == "1"
    assert switches[0]["to_track_id"] == "3"
    assert switches[0]["switch_frame"] == "100"
    assert switches[0]["actor_id"] == "A01"
    contract.validate_track_id_switches(switches, [_manifest_row()])


def test_no_switch_when_track_id_reused_by_same_actor():
    rows = [
        _segment_row(track_id="1", start_frame="0", end_frame="49"),
        _segment_row(track_id="1", start_frame="60", end_frame="99"),
    ]

    switches = derive_switches.derive_switch_rows(rows)

    assert switches == []


def test_rejects_unreviewed_segments():
    rows = [
        _segment_row(track_id="1", start_frame="0", end_frame="99", review_status="reviewed"),
        _segment_row(
            track_id="3", start_frame="100", end_frame="199", review_status="pending"
        ),
    ]

    with pytest.raises(ValueError, match="모든 Track segment"):
        derive_switches.derive_switch_rows(rows)


def test_rejects_reviewed_segments_without_actor_via_contract():
    rows = [
        _segment_row(track_id="1", start_frame="0", end_frame="99", actor_id="A01"),
        _segment_row(track_id="3", start_frame="100", end_frame="199", actor_id=""),
    ]

    with pytest.raises(ValueError, match="actor_id"):
        contract.validate_track_actor_segments(rows, [_manifest_row()])


def test_excludes_explicitly_reviewed_non_actor_track():
    rows = [
        _segment_row(track_id="1", start_frame="0", end_frame="49"),
        _segment_row(
            track_id="99",
            start_frame="50",
            end_frame="50",
            actor_id="",
            notes=contract.NON_ACTOR_TRACK_NOTE,
        ),
        _segment_row(track_id="1", start_frame="51", end_frame="99"),
    ]

    switches = derive_switches.derive_switch_rows(rows)

    assert switches == []


def test_marks_long_gap_transition_needs_review():
    rows = [
        _segment_row(track_id="1", start_frame="0", end_frame="49"),
        _segment_row(track_id="3", start_frame="80", end_frame="120"),
    ]

    switches = derive_switches.derive_switch_rows(rows, max_continuity_gap_frames=5)

    assert switches[0]["review_status"] == "needs_review"
    assert "gap_frames=30" in switches[0]["notes"]


def test_rejects_negative_continuity_gap():
    with pytest.raises(ValueError, match="0 이상"):
        derive_switches.derive_switch_rows([], max_continuity_gap_frames=-1)


def test_separates_switches_per_actor():
    rows = [
        _segment_row(track_id="1", start_frame="0", end_frame="49", actor_id="A01"),
        _segment_row(track_id="2", start_frame="0", end_frame="49", actor_id="A02"),
        _segment_row(track_id="4", start_frame="50", end_frame="99", actor_id="A01"),
        _segment_row(track_id="5", start_frame="50", end_frame="99", actor_id="A02"),
    ]

    switches = derive_switches.derive_switch_rows(rows)

    assert len(switches) == 2
    by_actor = {row["actor_id"]: row for row in switches}
    assert by_actor["A01"]["from_track_id"] == "1"
    assert by_actor["A01"]["to_track_id"] == "4"
    assert by_actor["A02"]["from_track_id"] == "2"
    assert by_actor["A02"]["to_track_id"] == "5"


def test_switch_id_is_deterministic_and_unique():
    rows = [
        _segment_row(track_id="1", start_frame="0", end_frame="99"),
        _segment_row(track_id="3", start_frame="100", end_frame="199"),
    ]

    first = derive_switches.derive_switch_rows(rows)
    second = derive_switches.derive_switch_rows(rows)

    assert first == second
    assert first[0]["switch_id"] == "sw_P4_S01_A01_contact_fall_01_cam01_1_3_100"
