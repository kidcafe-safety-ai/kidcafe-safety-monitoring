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


def test_csv_writer_is_atomic_and_requires_force(tmp_path):
    output = tmp_path / "manifest.csv"
    rows = [_manifest_row()]
    contract.write_csv_atomic(output, contract.MANIFEST_FIELDS, rows)

    with output.open(encoding="utf-8", newline="") as file:
        assert list(csv.DictReader(file)) == rows
    with pytest.raises(FileExistsError):
        contract.write_csv_atomic(output, contract.MANIFEST_FIELDS, rows)
