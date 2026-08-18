from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import phase4_recording_contract as contract  # noqa: E402
import review_phase4_track_actor_segments as review_segments  # noqa: E402


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


def _segment_row(**overrides) -> dict[str, str]:
    row = {
        "run_id": "run_test",
        "video_id": "P4_S01_A01_contact_fall_01_cam01",
        "start_frame": "0",
        "end_frame": "99",
        "track_id": "1",
        "actor_id": "",
        "review_status": "pending",
        "notes": contract.SCENARIO_SEEDED_DRAFT_NOTE,
    }
    row.update(overrides)
    return row


def _cache_video() -> dict:
    return {
        "video_id": "P4_S01_A01_contact_fall_01_cam01",
        "frame_count": 300,
        "frames": [
            {
                "frame_number": 0,
                "tracks": [
                    {"track_id": 1, "bbox": [10.0, 20.0, 30.0, 40.0]},
                    {"track_id": 2, "bbox": [50.0, 60.0, 70.0, 80.0]},
                ],
            }
        ],
    }


def _write_inputs(
    tmp_path: Path, *, manifest_rows=None, segment_rows=None
) -> tuple[Path, Path, Path]:
    manifest_path = tmp_path / "recordings_manifest.csv"
    segments_path = tmp_path / "track_actor_segments.csv"
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    contract.write_csv_atomic(
        manifest_path, contract.MANIFEST_FIELDS, manifest_rows or [_manifest_row()]
    )
    contract.write_csv_atomic(
        segments_path,
        contract.TRACK_ACTOR_SEGMENT_FIELDS,
        segment_rows or [_segment_row()],
    )
    (cache_dir / "P4_S01_A01_contact_fall_01_cam01.json").write_text(
        json.dumps(_cache_video()), encoding="utf-8"
    )
    return manifest_path, segments_path, cache_dir


def _session(tmp_path: Path, **kwargs) -> review_segments.ReviewSession:
    manifest_path, segments_path, cache_dir = _write_inputs(
        tmp_path,
        manifest_rows=kwargs.get("manifest_rows"),
        segment_rows=kwargs.get("segment_rows"),
    )
    return review_segments.ReviewSession(
        manifest_path=manifest_path,
        segments_path=segments_path,
        cache_dir=cache_dir,
        repo_root=tmp_path,
        video_id=kwargs.get("video_id", "P4_S01_A01_contact_fall_01_cam01"),
        include_reviewed=kwargs.get("include_reviewed", False),
    )


def test_rejects_unknown_video_id(tmp_path):
    with pytest.raises(ValueError, match="manifest에 없는 video_id"):
        _session(tmp_path, video_id="P4_S01_A99_contact_fall_01_cam01")


def test_rejects_missing_cache_file(tmp_path):
    manifest_path = tmp_path / "recordings_manifest.csv"
    segments_path = tmp_path / "track_actor_segments.csv"
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    contract.write_csv_atomic(manifest_path, contract.MANIFEST_FIELDS, [_manifest_row()])
    contract.write_csv_atomic(
        segments_path, contract.TRACK_ACTOR_SEGMENT_FIELDS, [_segment_row()]
    )

    with pytest.raises(ValueError, match="cache 파일이 없습니다"):
        review_segments.ReviewSession(
            manifest_path=manifest_path,
            segments_path=segments_path,
            cache_dir=cache_dir,
            repo_root=tmp_path,
            video_id="P4_S01_A01_contact_fall_01_cam01",
        )


def test_rejects_when_nothing_left_to_review(tmp_path):
    with pytest.raises(ValueError, match="검수할 segment"):
        _session(
            tmp_path,
            segment_rows=[_segment_row(actor_id="A01", review_status="reviewed")],
        )


def test_include_reviewed_reopens_completed_segment(tmp_path):
    session = _session(
        tmp_path,
        segment_rows=[_segment_row(actor_id="A01", review_status="reviewed")],
        include_reviewed=True,
    )

    assert session.current["review_status"] == "reviewed"


def test_assign_and_clear_actor(tmp_path):
    session = _session(tmp_path)

    session.assign_actor("A01")
    assert session.current["actor_id"] == "A01"

    session.clear_actor()
    assert session.current["actor_id"] == ""


def test_non_actor_track_can_be_approved(tmp_path):
    session = _session(tmp_path)

    session.assign_non_actor()
    assert session.approve() == "reviewed"
    assert session.current["actor_id"] == ""
    assert contract.NON_ACTOR_TRACK_NOTE in session.current["notes"]


def test_actor_assignment_clears_non_actor_marker(tmp_path):
    session = _session(tmp_path)

    session.assign_non_actor()
    session.assign_actor("A01")

    assert contract.NON_ACTOR_TRACK_NOTE not in session.current["notes"]


def test_rejects_actor_outside_video_manifest(tmp_path):
    session = _session(tmp_path)

    with pytest.raises(ValueError, match="manifest actor_ids"):
        session.assign_actor("A03")


def test_approve_requires_actor_id(tmp_path):
    session = _session(tmp_path)

    with pytest.raises(ValueError, match="actor_id"):
        session.approve()
    assert session.current["review_status"] == "pending"


def test_approve_marks_reviewed_and_strips_seeded_note(tmp_path):
    session = _session(tmp_path)
    session.assign_actor("A02")

    assert session.approve() == "reviewed"
    assert session.current["review_status"] == "reviewed"
    assert session.current["notes"] == ""


def test_mark_needs_review(tmp_path):
    session = _session(tmp_path)
    session.mark_needs_review()
    assert session.current["review_status"] == "needs_review"


def test_segments_sorted_by_start_frame_then_track_id(tmp_path):
    rows = [
        _segment_row(track_id="2", start_frame="50", end_frame="99"),
        _segment_row(track_id="1", start_frame="0", end_frame="49"),
    ]
    session = _session(tmp_path, segment_rows=rows)

    assert session.current["track_id"] == "1"
    assert session.go_next() is True
    assert session.current["track_id"] == "2"
    assert session.go_next() is False


def test_tracks_at_returns_cached_bboxes_for_overlay(tmp_path):
    session = _session(tmp_path)

    tracks = session.tracks_at(0)

    assert {track["track_id"] for track in tracks} == {1, 2}


def test_save_persists_and_validates(tmp_path):
    session = _session(tmp_path)
    session.assign_actor("A01")
    session.approve()
    session.save()

    rows = contract.load_track_actor_segments(session.segments_path, session.manifest_rows)
    assert rows[0]["actor_id"] == "A01"
    assert rows[0]["review_status"] == "reviewed"


def test_frame_at_uses_cache_for_backward_navigation(tmp_path, monkeypatch):
    manifest_path, segments_path, cache_dir = _write_inputs(tmp_path)
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

    monkeypatch.setattr(review_segments.cv2, "VideoCapture", FakeCapture)
    session = review_segments.ReviewSession(
        manifest_path=manifest_path,
        segments_path=segments_path,
        cache_dir=cache_dir,
        repo_root=tmp_path,
        video_id="P4_S01_A01_contact_fall_01_cam01",
    )

    forward = session.frame_at(10)
    backward = session.frame_at(9)

    assert forward.shape == (24, 32, 3)
    assert backward.shape == (24, 32, 3)
    assert len(captures) == 1


def test_frame_at_rewinds_for_uncached_earlier_frame(tmp_path, monkeypatch):
    manifest_path, segments_path, cache_dir = _write_inputs(tmp_path)
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

    monkeypatch.setattr(review_segments.cv2, "VideoCapture", FakeCapture)
    session = review_segments.ReviewSession(
        manifest_path=manifest_path,
        segments_path=segments_path,
        cache_dir=cache_dir,
        repo_root=tmp_path,
        video_id="P4_S01_A01_contact_fall_01_cam01",
    )

    session.frame_at(10)
    session._frame_cache.pop(5)
    earlier = session.frame_at(5)

    assert earlier.shape == (24, 32, 3)
    assert len(captures) == 2
