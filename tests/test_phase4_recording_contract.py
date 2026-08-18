from __future__ import annotations

import csv
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

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
        "video_path": (
            "data/datasets/phase4_recordings/a_fall_review/"
            "P4_S01_A01_fall_backward_01_cam01.mp4"
        ),
        "fps": "29.97",
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


def _annotation_row(**overrides) -> dict[str, str]:
    row = {
        "video_id": "P4_S01_A01_fall_backward_01_cam01",
        "label": "fall",
        "fall_start_frame": "80",
        "impact_frame": "92",
        "lying_start_frame": "108",
        "recovery_frame": "180",
        "victim_actor_id": "A01",
        "contact_occurred": "false",
        "cause_candidate_exists": "false",
        "cause_actor_id": "",
        "contact_frame": "",
        "review_status": "reviewed",
        "reviewer_id": "R01",
        "second_reviewer_id": "R02",
        "notes": "",
    }
    row.update(overrides)
    return row


class TestRecordingName:
    def test_parses_contract_filename(self):
        parsed = contract.parse_recording_name(
            "P4_S01_A03_fall_forward_knees_02_cam01.mp4"
        )

        assert parsed.session_id == "S01"
        assert parsed.primary_actor_id == "A03"
        assert parsed.scenario_type == "fall_forward_knees"
        assert parsed.take == "02"
        assert parsed.camera_id == "cam01"

    @pytest.mark.parametrize(
        "value",
        [
            "P4_S1_A01_fall_01_cam01.mp4",
            "P4_S01_A01_Fall_01_cam01.mp4",
            "P4_S01_A01_fall_T01_cam01.mp4",
            "P4_S01_A01_fall_01_camera01.mp4",
        ],
    )
    def test_rejects_non_contract_filename(self, value):
        with pytest.raises(ValueError, match="계약"):
            contract.parse_recording_name(value)


class TestManifestValidation:
    def test_accepts_valid_manifest(self):
        contract.validate_recordings_manifest([_manifest_row()])

    def test_rejects_filename_field_drift(self):
        with pytest.raises(ValueError, match="scenario_type"):
            contract.validate_recordings_manifest(
                [_manifest_row(scenario_type="fall_side")]
            )

    def test_rejects_primary_actor_outside_actor_ids(self):
        with pytest.raises(ValueError, match="primary_actor_id"):
            contract.validate_recordings_manifest(
                [_manifest_row(actor_ids="A02")]
            )

    def test_rejects_duplicate_content_checksum(self):
        second = _manifest_row(
            video_id="P4_S01_A02_fall_backward_01_cam01",
            actor_ids="A02",
            primary_actor_id="A02",
            video_path=(
                "data/datasets/phase4_recordings/a_fall_review/"
                "P4_S01_A02_fall_backward_01_cam01.mp4"
            ),
        )
        with pytest.raises(ValueError, match="동일한 영상 checksum"):
            contract.validate_recordings_manifest([_manifest_row(), second])

    @pytest.mark.parametrize(
        "video_path",
        [
            "/tmp/video.mp4",
            "../outside/video.mp4",
            r"data\video.mp4",
        ],
    )
    def test_rejects_unsafe_video_path(self, video_path):
        with pytest.raises(ValueError, match="상대 POSIX"):
            contract.validate_recordings_manifest([_manifest_row(video_path=video_path)])

    def test_verifies_real_file_checksum(self, tmp_path):
        video_path = tmp_path / "P4_S01_A01_fall_backward_01_cam01.mp4"
        video_path.write_bytes(b"recording")
        row = _manifest_row(
            video_path=video_path.relative_to(tmp_path).as_posix(),
            checksum_sha256=contract.sha256_file(video_path),
        )

        contract.validate_recordings_manifest(
            [row],
            repo_root=tmp_path,
            verify_files=True,
            verify_checksums=True,
        )

    def test_rejects_checksum_mismatch(self, tmp_path):
        video_path = tmp_path / "P4_S01_A01_fall_backward_01_cam01.mp4"
        video_path.write_bytes(b"recording")
        row = _manifest_row(video_path=video_path.name)

        with pytest.raises(ValueError, match="SHA-256"):
            contract.validate_recordings_manifest(
                [row],
                repo_root=tmp_path,
                verify_files=True,
                verify_checksums=True,
            )


class TestFallCauseValidation:
    def test_accepts_reviewed_fall(self):
        contract.validate_fall_cause_annotations(
            [_annotation_row()],
            [_manifest_row()],
            require_reviewed=True,
        )

    def test_accepts_incomplete_pending_draft(self):
        pending = _annotation_row(
            fall_start_frame="",
            impact_frame="",
            lying_start_frame="",
            recovery_frame="",
            contact_occurred="true",
            cause_candidate_exists="true",
            cause_actor_id="",
            contact_frame="",
            review_status="pending",
            reviewer_id="",
            second_reviewer_id="",
        )

        contract.validate_fall_cause_annotations([pending], [_manifest_row()])

    def test_rejects_out_of_order_fall_frames(self):
        with pytest.raises(ValueError, match="fall_start_frame"):
            contract.validate_fall_cause_annotations(
                [_annotation_row(fall_start_frame="100", impact_frame="90")],
                [_manifest_row()],
            )

    def test_rejects_frame_outside_video(self):
        with pytest.raises(ValueError, match="frame 범위"):
            contract.validate_fall_cause_annotations(
                [_annotation_row(recovery_frame="300")],
                [_manifest_row()],
            )

    def test_rejects_fall_frames_on_no_fall_row(self):
        manifest = _manifest_row(
            video_id="P4_S01_A01_pick_up_01_cam01",
            scenario_type="pick_up",
            label="no_fall",
            video_path=(
                "data/datasets/phase4_recordings/a_fall_review/"
                "P4_S01_A01_pick_up_01_cam01.mp4"
            ),
        )
        annotation = _annotation_row(
            video_id=manifest["video_id"],
            label="no_fall",
            victim_actor_id="",
        )

        with pytest.raises(ValueError, match="no_fall"):
            contract.validate_fall_cause_annotations([annotation], [manifest])

    def test_requires_distinct_reviewers_when_reviewed(self):
        with pytest.raises(ValueError, match="reviewer"):
            contract.validate_fall_cause_annotations(
                [_annotation_row(second_reviewer_id="R01")],
                [_manifest_row()],
            )

    def test_requires_contact_frame_for_reviewed_contact(self):
        with pytest.raises(ValueError, match="contact_frame"):
            contract.validate_fall_cause_annotations(
                [_annotation_row(contact_occurred="true")],
                [_manifest_row()],
            )

    def test_rejects_contact_frame_when_boolean_is_pending(self):
        with pytest.raises(ValueError, match="contact_occurred=true"):
            contract.validate_fall_cause_annotations(
                [
                    _annotation_row(
                        contact_occurred="",
                        contact_frame="70",
                        review_status="pending",
                    )
                ],
                [_manifest_row()],
            )

    def test_rejects_cause_actor_equal_to_victim(self):
        with pytest.raises(ValueError, match="달라야"):
            contract.validate_fall_cause_annotations(
                [
                    _annotation_row(
                        cause_candidate_exists="true",
                        cause_actor_id="A01",
                    )
                ],
                [_manifest_row()],
            )

    def test_requires_annotation_for_every_manifest_video(self):
        second = _manifest_row(
            video_id="P4_S01_A02_fall_side_01_cam01",
            actor_ids="A02",
            primary_actor_id="A02",
            scenario_type="fall_side",
            video_path=(
                "data/datasets/phase4_recordings/a_fall_review/"
                "P4_S01_A02_fall_side_01_cam01.mp4"
            ),
            checksum_sha256="b" * 64,
        )
        with pytest.raises(ValueError, match="누락"):
            contract.validate_fall_cause_annotations(
                [_annotation_row()],
                [_manifest_row(), second],
            )


def _segment_row(**overrides) -> dict[str, str]:
    row = {
        "run_id": "run_e1_diagnostic",
        "video_id": "P4_S01_A01_fall_backward_01_cam01",
        "start_frame": "0",
        "end_frame": "99",
        "track_id": "1",
        "actor_id": "A01",
        "review_status": "reviewed",
        "notes": "",
    }
    row.update(overrides)
    return row


def _switch_row(**overrides) -> dict[str, str]:
    row = {
        "run_id": "run_e1_diagnostic",
        "switch_id": "switch_001",
        "video_id": "P4_S01_A01_fall_backward_01_cam01",
        "actor_id": "A01",
        "from_track_id": "1",
        "to_track_id": "2",
        "switch_frame": "100",
        "review_status": "reviewed",
        "notes": "",
    }
    row.update(overrides)
    return row


class TestTrackActorSegmentValidation:
    def test_accepts_reviewed_segment(self):
        contract.validate_track_actor_segments([_segment_row()], [_manifest_row()])

    def test_accepts_pending_segment_without_actor(self):
        pending = _segment_row(actor_id="", review_status="pending")
        contract.validate_track_actor_segments([pending], [_manifest_row()])

    def test_rejects_reviewed_without_actor(self):
        with pytest.raises(ValueError, match="actor_id"):
            contract.validate_track_actor_segments(
                [_segment_row(actor_id="")], [_manifest_row()]
            )

    def test_accepts_reviewed_non_actor_track(self):
        row = _segment_row(
            actor_id="",
            notes=contract.NON_ACTOR_TRACK_NOTE,
        )

        contract.validate_track_actor_segments([row], [_manifest_row()])

    def test_rejects_start_after_end(self):
        with pytest.raises(ValueError, match="start_frame"):
            contract.validate_track_actor_segments(
                [_segment_row(start_frame="150", end_frame="99")], [_manifest_row()]
            )

    def test_rejects_frame_outside_video(self):
        with pytest.raises(ValueError, match="frame 범위"):
            contract.validate_track_actor_segments(
                [_segment_row(end_frame="300")], [_manifest_row()]
            )

    def test_rejects_unknown_video_id(self):
        with pytest.raises(ValueError, match="manifest에 없는 video_id"):
            contract.validate_track_actor_segments(
                [_segment_row(video_id="P4_S01_A99_fall_backward_01_cam01")],
                [_manifest_row()],
            )

    def test_rejects_overlapping_segments_for_same_track(self):
        second = _segment_row(start_frame="50", end_frame="150")
        with pytest.raises(ValueError, match="겹칩니다"):
            contract.validate_track_actor_segments(
                [_segment_row(), second], [_manifest_row()]
            )

    def test_accepts_adjacent_non_overlapping_segments_for_same_track(self):
        second = _segment_row(start_frame="100", end_frame="150")
        contract.validate_track_actor_segments([_segment_row(), second], [_manifest_row()])

    def test_accepts_different_tracks_with_overlapping_frames(self):
        other_actor = _segment_row(track_id="2", actor_id="A02")
        contract.validate_track_actor_segments(
            [_segment_row(), other_actor], [_manifest_row(actor_ids="A01|A02")]
        )

    def test_rejects_actor_outside_manifest(self):
        with pytest.raises(ValueError, match="manifest actor_ids"):
            contract.validate_track_actor_segments(
                [_segment_row(actor_id="A02")], [_manifest_row(actor_ids="A01")]
            )

    def test_rejects_overlapping_reviewed_segments_for_same_actor(self):
        duplicate_track = _segment_row(track_id="2", actor_id="A01")
        with pytest.raises(ValueError, match="actor_id=A01"):
            contract.validate_track_actor_segments(
                [_segment_row(), duplicate_track], [_manifest_row()]
            )


class TestTrackIdSwitchValidation:
    def test_accepts_reviewed_switch(self):
        contract.validate_track_id_switches([_switch_row()], [_manifest_row()])

    def test_accepts_empty_switches(self):
        contract.validate_track_id_switches([], [_manifest_row()])

    def test_rejects_same_from_and_to_track(self):
        with pytest.raises(ValueError, match="달라야"):
            contract.validate_track_id_switches(
                [_switch_row(to_track_id="1")], [_manifest_row()]
            )

    def test_rejects_switch_frame_outside_video(self):
        with pytest.raises(ValueError, match="frame 범위"):
            contract.validate_track_id_switches(
                [_switch_row(switch_frame="300")], [_manifest_row()]
            )

    def test_rejects_duplicate_switch_id(self):
        with pytest.raises(ValueError, match="중복"):
            contract.validate_track_id_switches(
                [_switch_row(), _switch_row(switch_frame="120")], [_manifest_row()]
            )

    def test_rejects_invalid_actor_id(self):
        with pytest.raises(ValueError, match="actor_id"):
            contract.validate_track_id_switches(
                [_switch_row(actor_id="bogus")], [_manifest_row()]
            )

    def test_rejects_switch_actor_outside_manifest(self):
        with pytest.raises(ValueError, match="manifest actor_ids"):
            contract.validate_track_id_switches(
                [_switch_row(actor_id="A02")], [_manifest_row(actor_ids="A01")]
            )


def _event_row(**overrides) -> dict[str, str]:
    row = {
        "run_id": "run_e1_diagnostic",
        "video_id": "P4_S01_A01_fall_backward_01_cam01",
        "event_frame": "131",
        "victim_track_id": "1",
        "victim_actor_id": "A01",
        "predicted_cause_track_id": "2",
        "predicted_cause_actor_id": "A02",
        "related_switch_ids": "",
        "id_switch_relation": "none",
        "event_error_type": "none",
        "review_status": "reviewed",
        "notes": "",
    }
    row.update(overrides)
    return row


class TestEventAttributionReviewValidation:
    def test_accepts_reviewed_event(self):
        contract.validate_event_attribution_review(
            [_event_row()], [_manifest_row(actor_ids="A01|A02")]
        )

    def test_accepts_empty_rows(self):
        contract.validate_event_attribution_review([], [_manifest_row()])

    def test_accepts_missed_fall_without_event_frame(self):
        row = _event_row(
            event_frame="",
            victim_track_id="",
            victim_actor_id="",
            predicted_cause_track_id="",
            predicted_cause_actor_id="",
            related_switch_ids="",
            id_switch_relation="none",
            event_error_type="missed_fall",
        )

        contract.validate_event_attribution_review([row], [_manifest_row(actor_ids="A01|A02")])

    def test_accepts_true_negative_without_event_fields(self):
        row = _event_row(
            event_frame="",
            victim_track_id="",
            victim_actor_id="",
            predicted_cause_track_id="",
            predicted_cause_actor_id="",
            related_switch_ids="",
            event_error_type="true_negative",
        )

        contract.validate_event_attribution_review(
            [row], [_manifest_row(label="no_fall", actor_ids="A01|A02")]
        )

    def test_accepts_false_alarm_on_no_fall_video(self):
        row = _event_row(event_error_type="false_alarm")

        contract.validate_event_attribution_review(
            [row], [_manifest_row(label="no_fall", actor_ids="A01|A02")]
        )

    @pytest.mark.parametrize("error_type", ["true_negative", "false_alarm"])
    def test_rejects_no_fall_outcome_on_fall_video(self, error_type):
        row = _event_row(event_error_type=error_type)
        if error_type == "true_negative":
            row.update(
                event_frame="",
                victim_track_id="",
                victim_actor_id="",
                predicted_cause_track_id="",
                predicted_cause_actor_id="",
            )

        with pytest.raises(ValueError, match="no_fall 영상에만"):
            contract.validate_event_attribution_review(
                [row], [_manifest_row(label="fall", actor_ids="A01|A02")]
            )

    def test_rejects_true_negative_with_event_fields(self):
        row = _event_row(event_error_type="true_negative")

        with pytest.raises(ValueError, match="필드는 비워야"):
            contract.validate_event_attribution_review(
                [row], [_manifest_row(label="no_fall", actor_ids="A01|A02")]
            )

    def test_rejects_missed_fall_on_no_fall_video(self):
        row = _event_row(
            event_frame="",
            victim_track_id="",
            victim_actor_id="",
            predicted_cause_track_id="",
            predicted_cause_actor_id="",
            event_error_type="missed_fall",
        )

        with pytest.raises(ValueError, match="fall 영상에만"):
            contract.validate_event_attribution_review(
                [row], [_manifest_row(label="no_fall", actor_ids="A01|A02")]
            )

    def test_rejects_unknown_video_id(self):
        with pytest.raises(ValueError, match="manifest에 없는 video_id"):
            contract.validate_event_attribution_review(
                [_event_row(video_id="P4_S01_A99_fall_backward_01_cam01")],
                [_manifest_row(actor_ids="A01|A02")],
            )

    def test_rejects_event_frame_outside_video(self):
        with pytest.raises(ValueError, match="frame 범위"):
            contract.validate_event_attribution_review(
                [_event_row(event_frame="300")], [_manifest_row(actor_ids="A01|A02")]
            )

    def test_rejects_actor_outside_manifest(self):
        with pytest.raises(ValueError, match="manifest actor_ids"):
            contract.validate_event_attribution_review(
                [_event_row(predicted_cause_actor_id="A02")], [_manifest_row(actor_ids="A01")]
            )

    def test_rejects_invalid_id_switch_relation(self):
        with pytest.raises(ValueError, match="id_switch_relation"):
            contract.validate_event_attribution_review(
                [_event_row(id_switch_relation="bogus")], [_manifest_row(actor_ids="A01|A02")]
            )

    def test_rejects_invalid_event_error_type(self):
        with pytest.raises(ValueError, match="event_error_type"):
            contract.validate_event_attribution_review(
                [_event_row(event_error_type="bogus")], [_manifest_row(actor_ids="A01|A02")]
            )

    def test_rejects_non_missed_fall_error_type_without_event_frame(self):
        row = _event_row(event_frame="", event_error_type="false_attribution")
        with pytest.raises(ValueError, match="event_frame"):
            contract.validate_event_attribution_review(
                [row], [_manifest_row(actor_ids="A01|A02")]
            )

    def test_rejects_reviewed_without_classification(self):
        row = _event_row(event_error_type="", id_switch_relation="")
        with pytest.raises(ValueError, match="event_error_type"):
            contract.validate_event_attribution_review(
                [row], [_manifest_row(actor_ids="A01|A02")]
            )

    def test_accepts_pending_without_classification(self):
        row = _event_row(event_error_type="", id_switch_relation="", review_status="pending")
        contract.validate_event_attribution_review([row], [_manifest_row(actor_ids="A01|A02")])


def test_csv_writer_is_atomic_and_requires_force(tmp_path):
    output = tmp_path / "manifest.csv"
    rows = [_manifest_row()]
    contract.write_csv_atomic(output, contract.MANIFEST_FIELDS, rows)

    with output.open(encoding="utf-8", newline="") as file:
        assert list(csv.DictReader(file)) == rows
    with pytest.raises(FileExistsError):
        contract.write_csv_atomic(output, contract.MANIFEST_FIELDS, rows)
