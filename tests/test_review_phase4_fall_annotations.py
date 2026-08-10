from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import generate_phase4_fall_annotations as generate_annotations  # noqa: E402
import phase4_recording_contract as contract  # noqa: E402
import review_phase4_fall_annotations as review_annotations  # noqa: E402


def _manifest_row() -> dict[str, str]:
    return {
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


def _write_inputs(tmp_path: Path, *, include_no_fall: bool = False) -> tuple[Path, Path]:
    manifest_path = tmp_path / "recordings_manifest.csv"
    annotation_path = tmp_path / "fall_cause_annotations.csv"
    manifest_rows = [_manifest_row()]
    if include_no_fall:
        manifest_rows.append(
            {
                **_manifest_row(),
                "video_id": "P4_S01_A02_pick_up_01_cam01",
                "actor_ids": "A02",
                "primary_actor_id": "A02",
                "scenario_type": "pick_up",
                "label": "no_fall",
                "video_path": "data/P4_S01_A02_pick_up_01_cam01.mp4",
                "checksum_sha256": "b" * 64,
            }
        )
    annotation_rows = generate_annotations.build_annotation_rows(manifest_rows)
    contract.write_csv_atomic(
        manifest_path, contract.MANIFEST_FIELDS, manifest_rows
    )
    contract.write_csv_atomic(
        annotation_path, contract.FALL_CAUSE_FIELDS, annotation_rows
    )
    return manifest_path, annotation_path


def _session(
    tmp_path: Path,
    *,
    reviewer_id: str,
    review_pass: str,
) -> review_annotations.ReviewSession:
    manifest_path = tmp_path / "recordings_manifest.csv"
    annotation_path = tmp_path / "fall_cause_annotations.csv"
    return review_annotations.ReviewSession(
        manifest_path=manifest_path,
        annotations_path=annotation_path,
        repo_root=tmp_path,
        reviewer_id=reviewer_id,
        review_pass=review_pass,
    )


def _set_required_fall_frames(session: review_annotations.ReviewSession) -> None:
    session.set_frame("fall_start_frame", 80)
    session.set_frame("impact_frame", 92)
    session.set_frame("lying_start_frame", 108)
    session.set_frame("recovery_frame", 180)


def test_first_review_records_reviewer_but_keeps_pending(tmp_path):
    _write_inputs(tmp_path)
    session = _session(tmp_path, reviewer_id="R01", review_pass="first")
    _set_required_fall_frames(session)

    assert session.approve() == "first_review_complete"
    session.save()

    rows = contract.load_fall_cause_annotations(
        tmp_path / "fall_cause_annotations.csv", [_manifest_row()]
    )
    assert rows[0]["review_status"] == "pending"
    assert rows[0]["reviewer_id"] == "R01"
    assert rows[0]["second_reviewer_id"] == ""


def test_first_review_rejects_missing_frames(tmp_path):
    _write_inputs(tmp_path)
    session = _session(tmp_path, reviewer_id="R01", review_pass="first")

    with pytest.raises(ValueError, match="필수 frame"):
        session.approve()


def test_second_review_without_changes_marks_reviewed(tmp_path):
    _write_inputs(tmp_path)
    first = _session(tmp_path, reviewer_id="R01", review_pass="first")
    _set_required_fall_frames(first)
    first.approve()
    first.save()

    second = _session(tmp_path, reviewer_id="R02", review_pass="second")
    assert second.approve() == "reviewed"
    second.save()

    rows = contract.load_fall_cause_annotations(
        tmp_path / "fall_cause_annotations.csv",
        [_manifest_row()],
        require_reviewed=True,
    )
    assert rows[0]["reviewer_id"] == "R01"
    assert rows[0]["second_reviewer_id"] == "R02"
    assert rows[0]["notes"] == ""


def test_second_review_change_requires_resolution(tmp_path):
    _write_inputs(tmp_path)
    first = _session(tmp_path, reviewer_id="R01", review_pass="first")
    _set_required_fall_frames(first)
    first.approve()
    first.save()

    second = _session(tmp_path, reviewer_id="R02", review_pass="second")
    second.set_frame("impact_frame", 93)

    assert second.approve() == "needs_review"
    assert second.current["review_status"] == "needs_review"
    assert "second reviewer changed" in second.current["notes"]


def test_second_review_change_survives_navigation(tmp_path):
    _write_inputs(tmp_path, include_no_fall=True)
    first = _session(tmp_path, reviewer_id="R01", review_pass="first")
    _set_required_fall_frames(first)
    first.approve()
    assert first.go_next()
    first.approve()
    first.save()

    second = _session(tmp_path, reviewer_id="R02", review_pass="second")
    second.set_frame("impact_frame", 93)
    assert second.go_next()
    assert second.go_previous()

    assert second.approve() == "needs_review"


def test_same_reviewer_cannot_run_second_pass(tmp_path):
    _write_inputs(tmp_path)
    first = _session(tmp_path, reviewer_id="R01", review_pass="first")
    _set_required_fall_frames(first)
    first.approve()
    first.save()

    with pytest.raises(ValueError, match="같습니다"):
        _session(tmp_path, reviewer_id="R01", review_pass="second")


def test_clear_frame_and_cause_toggles_are_consistent(tmp_path):
    _write_inputs(tmp_path)
    session = _session(tmp_path, reviewer_id="R01", review_pass="first")
    session.set_frame("contact_frame", 70)
    session.toggle_contact()
    session.toggle_cause_candidate()

    assert session.current["contact_occurred"] == "true"
    assert session.current["contact_frame"] == "70"
    assert session.current["cause_candidate_exists"] == "true"
    session.toggle_contact()
    session.toggle_cause_candidate()
    assert session.current["contact_frame"] == ""
    assert session.current["cause_actor_id"] == ""


def test_no_fall_rejects_fall_timing_frame_input(tmp_path):
    _write_inputs(tmp_path, include_no_fall=True)
    session = _session(tmp_path, reviewer_id="R01", review_pass="first")
    assert session.go_next()

    with pytest.raises(ValueError, match="no_fall"):
        session.set_frame("lying_start_frame", 100)

    session.set_frame("contact_frame", 90)
    assert session.current["contact_frame"] == "90"


def test_backward_navigation_uses_compressed_frame_cache(tmp_path, monkeypatch):
    _write_inputs(tmp_path)
    video_path = tmp_path / _manifest_row()["video_path"]
    video_path.parent.mkdir(parents=True)
    video_path.touch()

    captures = []

    class FakeCapture:
        def __init__(self, _path):
            self.read_count = 0
            self.released = False
            captures.append(self)

        def isOpened(self):
            return True

        def read(self):
            value = self.read_count % 255
            self.read_count += 1
            return True, np.full((24, 32, 3), value, dtype=np.uint8)

        def release(self):
            self.released = True

    monkeypatch.setattr(review_annotations.cv2, "VideoCapture", FakeCapture)
    session = _session(tmp_path, reviewer_id="R01", review_pass="first")

    forward = session.frame_at(10)
    reads_after_forward = captures[0].read_count
    backward = session.frame_at(9)

    assert forward.shape == (24, 32, 3)
    assert backward.shape == (24, 32, 3)
    assert len(captures) == 1
    assert captures[0].read_count == reads_after_forward == 11
