from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import export_phase4_track_id_switch_snapshots as export_snapshots  # noqa: E402


def _segment_row(**overrides) -> dict[str, str]:
    row = {
        "run_id": "run_test",
        "video_id": "vid",
        "start_frame": "0",
        "end_frame": "50",
        "track_id": "1",
        "actor_id": "A01",
        "review_status": "reviewed",
        "notes": "",
    }
    row.update(overrides)
    return row


def test_finds_the_latest_segment_ending_before_the_switch():
    rows = [
        _segment_row(track_id="1", start_frame="0", end_frame="50"),
        _segment_row(track_id="1", start_frame="60", end_frame="80"),
        _segment_row(track_id="3", start_frame="120", end_frame="150"),
    ]

    result = export_snapshots.find_previous_segment_end_frame(
        rows, video_id="vid", actor_id="A01", track_id="1", before_frame=100
    )

    assert result == 80


def test_returns_none_when_no_matching_segment():
    rows = [_segment_row(track_id="1", start_frame="0", end_frame="50")]

    result = export_snapshots.find_previous_segment_end_frame(
        rows, video_id="vid", actor_id="A01", track_id="2", before_frame=100
    )

    assert result is None


def test_ignores_other_videos_and_actors():
    rows = [
        _segment_row(video_id="other", track_id="1", end_frame="90"),
        _segment_row(actor_id="A02", track_id="1", end_frame="95"),
        _segment_row(video_id="vid", actor_id="A01", track_id="1", end_frame="40"),
    ]

    result = export_snapshots.find_previous_segment_end_frame(
        rows, video_id="vid", actor_id="A01", track_id="1", before_frame=100
    )

    assert result == 40
