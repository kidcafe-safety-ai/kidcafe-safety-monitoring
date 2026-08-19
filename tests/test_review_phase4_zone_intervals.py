from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import phase4_recording_contract as contract  # noqa: E402
import review_phase4_zone_intervals as review_intervals  # noqa: E402


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


def _interval_row(**overrides) -> dict[str, str]:
    row = {
        "video_id": "P4_S01_A01_zone_enter_exit_01_cam01",
        "zone_id": "play_floor",
        "interval_index": "1",
        "enter_frame": "",
        "exit_frame": "",
        "dwell_start_frame": "",
        "review_status": "pending",
        "notes": contract.SCENARIO_SEEDED_DRAFT_NOTE,
    }
    row.update(overrides)
    return row


_ZONE_POLYGON = [[0.25, 0.25], [0.75, 0.25], [0.75, 0.75], [0.25, 0.75]]


def _write_inputs(
    tmp_path: Path,
    *,
    manifest_rows=None,
    interval_rows=None,
    zone_points=None,
) -> tuple[Path, Path, Path]:
    manifest_path = tmp_path / "recordings_manifest.csv"
    intervals_path = tmp_path / "zone_intervals.csv"
    zone_path = tmp_path / "image_zone.json"

    contract.write_csv_atomic(
        manifest_path, contract.MANIFEST_FIELDS, manifest_rows or [_manifest_row()]
    )
    contract.write_csv_atomic(
        intervals_path,
        contract.ZONE_INTERVAL_FIELDS,
        interval_rows or [_interval_row()],
    )
    zone_path.write_text(
        json.dumps(
            [{"zone_id": "play_floor", "points": zone_points or _ZONE_POLYGON}]
        ),
        encoding="utf-8",
    )
    return manifest_path, intervals_path, zone_path


def _session(tmp_path: Path, **kwargs) -> review_intervals.ReviewSession:
    manifest_path, intervals_path, zone_path = _write_inputs(tmp_path, **{
        key: value
        for key, value in kwargs.items()
        if key in {"manifest_rows", "interval_rows", "zone_points"}
    })
    return review_intervals.ReviewSession(
        manifest_path=manifest_path,
        intervals_path=intervals_path,
        repo_root=tmp_path,
        video_id=kwargs.get("video_id", "P4_S01_A01_zone_enter_exit_01_cam01"),
        image_zone_path=zone_path,
        show_zone_reference=kwargs.get("show_zone_reference", False),
        include_reviewed=kwargs.get("include_reviewed", False),
    )


def test_rejects_unknown_video_id(tmp_path):
    with pytest.raises(ValueError, match="manifest에 없는 video_id"):
        _session(tmp_path, video_id="P4_S01_A99_zone_enter_exit_01_cam01")


def test_rejects_image_zone_missing_the_target_zone_id(tmp_path):
    manifest_path, intervals_path, zone_path = _write_inputs(tmp_path)
    zone_path.write_text(
        json.dumps([{"zone_id": "danger_door", "points": _ZONE_POLYGON}]),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="play_floor"):
        review_intervals.ReviewSession(
            manifest_path=manifest_path,
            intervals_path=intervals_path,
            repo_root=tmp_path,
            video_id="P4_S01_A01_zone_enter_exit_01_cam01",
            image_zone_path=zone_path,
            show_zone_reference=True,
        )


def test_rejects_when_nothing_left_to_review(tmp_path):
    with pytest.raises(ValueError, match="검수할 interval"):
        _session(tmp_path, interval_rows=[_interval_row(
            enter_frame="40", exit_frame="150", review_status="reviewed"
        )])


def test_include_reviewed_reopens_completed_interval(tmp_path):
    session = _session(
        tmp_path,
        interval_rows=[_interval_row(
            enter_frame="40", exit_frame="150", review_status="reviewed"
        )],
        include_reviewed=True,
    )

    assert session.current["review_status"] == "reviewed"


def test_set_and_clear_frame_round_trip(tmp_path):
    session = _session(tmp_path)

    session.set_frame("enter_frame", 40)
    session.set_frame("exit_frame", 150)
    session.set_frame("dwell_start_frame", 60)
    assert session.current["enter_frame"] == "40"
    assert session.current["exit_frame"] == "150"
    assert session.current["dwell_start_frame"] == "60"

    session.clear_frame("dwell_start_frame")
    assert session.current["dwell_start_frame"] == ""


def test_set_frame_clamps_to_video_bounds(tmp_path):
    session = _session(tmp_path)

    session.set_frame("enter_frame", -5)
    assert session.current["enter_frame"] == "0"

    session.set_frame("exit_frame", 10_000)
    assert session.current["exit_frame"] == "299"


def test_approve_requires_enter_and_exit(tmp_path):
    session = _session(tmp_path)

    with pytest.raises(ValueError, match="enter_frame"):
        session.approve()
    assert session.current["review_status"] == "pending"


def test_approve_marks_reviewed_and_strips_seeded_note(tmp_path):
    session = _session(tmp_path)
    session.set_frame("enter_frame", 40)
    session.set_frame("exit_frame", 150)

    assert session.approve() == "reviewed"
    assert session.current["review_status"] == "reviewed"
    assert session.current["notes"] == (
        "review_mode=blind; zone_reference=hidden; dwell_threshold_sec=5"
    )


def test_approve_records_visible_reference_for_adjudication(tmp_path):
    session = _session(tmp_path, show_zone_reference=True)
    session.set_frame("enter_frame", 40)
    session.set_frame("exit_frame", 150)

    session.approve()

    assert session.current["notes"] == (
        "review_mode=adjudication; zone_reference=visible; dwell_threshold_sec=5"
    )


def test_reapproval_replaces_review_provenance_without_duplicates(tmp_path):
    session = _session(tmp_path)
    session.set_frame("enter_frame", 40)
    session.set_frame("exit_frame", 150)

    session.approve()
    session.approve()

    assert session.current["notes"] == (
        "review_mode=blind; zone_reference=hidden; dwell_threshold_sec=5"
    )


def test_approve_clears_dwell_when_threshold_is_not_reached(tmp_path):
    session = _session(tmp_path)
    session.set_frame("enter_frame", 0)
    session.set_frame("exit_frame", 299)

    session.approve()

    assert session.current["dwell_start_frame"] == ""


def test_approve_derives_dwell_when_threshold_is_reached(tmp_path):
    session = _session(
        tmp_path,
        manifest_rows=[_manifest_row(frame_count="400")],
    )
    session.set_frame("enter_frame", 40)
    session.set_frame("exit_frame", 350)

    session.approve()

    assert session.current["dwell_start_frame"] == "340"


def test_approve_rejects_enter_not_before_exit(tmp_path):
    session = _session(tmp_path)
    session.set_frame("enter_frame", 150)
    session.set_frame("exit_frame", 150)

    with pytest.raises(ValueError, match="enter_frame"):
        session.approve()
    assert session.current["review_status"] == "pending"


def test_mark_needs_review(tmp_path):
    session = _session(tmp_path)
    session.mark_needs_review()
    assert session.current["review_status"] == "needs_review"


def test_add_interval_increments_index_and_inserts_after_current(tmp_path):
    session = _session(tmp_path)
    session.set_frame("enter_frame", 40)
    session.set_frame("exit_frame", 150)
    session.approve()

    session.add_interval()

    assert session.current["interval_index"] == "2"
    assert session.current["enter_frame"] == ""
    assert session.current["review_status"] == "pending"
    assert len(session.all_rows) == 2
    assert [row["interval_index"] for row in session.all_rows] == ["1", "2"]


def test_navigation_bounds(tmp_path):
    session = _session(tmp_path)
    assert session.go_previous() is False
    session.add_interval()
    assert session.go_previous() is True
    assert session.go_next() is True
    assert session.go_next() is False


def test_zone_polygon_px_scales_by_manifest_resolution(tmp_path):
    session = _session(tmp_path, show_zone_reference=True)

    polygon = session.zone_polygon_px()

    assert polygon.tolist() == [[480, 270], [1440, 270], [1440, 810], [480, 810]]


def test_blind_review_does_not_load_zone_polygon(tmp_path):
    session = _session(tmp_path)

    assert session.zone_polygon_px() is None


def test_save_persists_and_validates(tmp_path):
    session = _session(tmp_path)
    session.set_frame("enter_frame", 40)
    session.set_frame("exit_frame", 150)
    session.approve()
    session.save()

    rows = contract.load_zone_intervals(session.intervals_path, session.manifest_rows)
    assert rows[0]["enter_frame"] == "40"
    assert rows[0]["review_status"] == "reviewed"


def test_frame_at_uses_cache_for_backward_navigation(tmp_path, monkeypatch):
    manifest_path, intervals_path, zone_path = _write_inputs(tmp_path)
    video_path = tmp_path / _manifest_row()["video_path"]
    video_path.parent.mkdir(parents=True, exist_ok=True)
    video_path.touch()

    captures = []

    class FakeCapture:
        def __init__(self, _path):
            self.read_count = 0
            captures.append(self)

        def isOpened(self):
            return True

        def read(self):
            value = self.read_count % 255
            self.read_count += 1
            return True, np.full((24, 32, 3), value, dtype=np.uint8)

        def release(self):
            pass

    monkeypatch.setattr(review_intervals.cv2, "VideoCapture", FakeCapture)
    session = review_intervals.ReviewSession(
        manifest_path=manifest_path,
        intervals_path=intervals_path,
        repo_root=tmp_path,
        video_id="P4_S01_A01_zone_enter_exit_01_cam01",
        image_zone_path=zone_path,
    )

    forward = session.frame_at(10)
    backward = session.frame_at(9)

    assert forward.shape == (24, 32, 3)
    assert backward.shape == (24, 32, 3)
    assert len(captures) == 1
