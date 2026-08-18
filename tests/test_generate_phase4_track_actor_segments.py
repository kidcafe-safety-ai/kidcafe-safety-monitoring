from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import generate_phase4_track_actor_segments as generate_segments  # noqa: E402
import phase4_recording_contract as contract  # noqa: E402


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


def _cache_video(frame_track_ids: list[list[int]], *, frame_count: int = 300) -> dict:
    frames = [
        {"frame_number": index, "tracks": [{"track_id": tid} for tid in track_ids]}
        for index, track_ids in enumerate(frame_track_ids)
    ]
    return {
        "cache_schema_version": 1,
        "video_id": "P4_S01_A01_contact_fall_01_cam01",
        "frame_count": frame_count,
        "frames": frames,
    }


class TestExtractTrackSegments:
    def test_single_contiguous_track(self):
        cache_video = _cache_video([[1], [1], [1]])

        segments = generate_segments.extract_track_segments(cache_video)

        assert segments == [(1, 0, 2)]

    def test_splits_on_gap_by_default(self):
        cache_video = _cache_video([[1], [], [1]])

        segments = generate_segments.extract_track_segments(cache_video)

        assert segments == [(1, 0, 0), (1, 2, 2)]

    def test_merges_small_gap_when_tolerated(self):
        cache_video = _cache_video([[1], [], [], [1]])

        segments = generate_segments.extract_track_segments(cache_video, merge_gap_frames=2)

        assert segments == [(1, 0, 3)]

    def test_keeps_gap_larger_than_tolerance_separate(self):
        cache_video = _cache_video([[1], [], [], [], [1]])

        segments = generate_segments.extract_track_segments(cache_video, merge_gap_frames=2)

        assert segments == [(1, 0, 0), (1, 4, 4)]

    def test_rejects_negative_merge_gap(self):
        cache_video = _cache_video([[1]])
        with pytest.raises(ValueError, match="merge_gap_frames"):
            generate_segments.extract_track_segments(cache_video, merge_gap_frames=-1)

    def test_two_simultaneous_tracks_sorted_by_start(self):
        cache_video = _cache_video([[1, 2], [1, 2]])

        segments = generate_segments.extract_track_segments(cache_video)

        assert segments == [(1, 0, 1), (2, 0, 1)]


class TestSelectTargetVideoIds:
    def test_defaults_to_multi_person_scenarios_for_a01_a02(self):
        rows = [
            _manifest_row(),
            _manifest_row(
                video_id="P4_S01_A01_sit_down_01_cam01", scenario_type="sit_down", label="no_fall"
            ),
            _manifest_row(
                video_id="P4_S01_A03_contact_fall_01_cam01",
                primary_actor_id="A03",
                actor_ids="A02|A03",
            ),
        ]

        selected = generate_segments.select_target_video_ids(
            rows, scenarios=generate_segments.DEFAULT_SCENARIOS, explicit_video_ids=None
        )

        assert selected == ["P4_S01_A01_contact_fall_01_cam01"]

    def test_explicit_video_ids_override_scenario_filter(self):
        rows = [_manifest_row()]

        selected = generate_segments.select_target_video_ids(
            rows,
            scenarios=generate_segments.DEFAULT_SCENARIOS,
            explicit_video_ids=["P4_S01_A02_near_pass_01_cam01"],
        )

        assert selected == ["P4_S01_A02_near_pass_01_cam01"]


class TestBuildSegmentRows:
    def test_seeds_pending_rows_with_run_id(self, tmp_path):
        cache_dir = tmp_path
        (cache_dir / "P4_S01_A01_contact_fall_01_cam01.json").write_text(
            json.dumps(_cache_video([[1], [1]])), encoding="utf-8"
        )

        rows = generate_segments.build_segment_rows(
            cache_dir=cache_dir,
            video_ids=["P4_S01_A01_contact_fall_01_cam01"],
            run_id="run_test",
        )

        assert rows == [
            {
                "run_id": "run_test",
                "video_id": "P4_S01_A01_contact_fall_01_cam01",
                "start_frame": "0",
                "end_frame": "1",
                "track_id": "1",
                "actor_id": "",
                "review_status": "pending",
                "notes": contract.SCENARIO_SEEDED_DRAFT_NOTE,
            }
        ]
        contract.validate_track_actor_segments(rows, [_manifest_row(frame_count="300")])


class TestVerifyCacheIntegrity:
    def _write_selected_profile(self, path: Path, *, manifest_sha: str, annotations_sha: str):
        path.write_text(
            json.dumps(
                {
                    "model": {"sha256": "model-sha"},
                    "inference": {
                        "tracker": "pose",
                        "tracker_model_sha256": "tracker-sha",
                        "tracker_confidence": 0.5,
                        "fall_model_confidence": 0.5,
                    },
                    "recorded_dataset": {
                        "recordings_manifest_sha256": manifest_sha,
                        "fall_cause_annotations_sha256": annotations_sha,
                    },
                }
            ),
            encoding="utf-8",
        )

    def _cache_manifest(
        self,
        manifest_path: Path,
        annotations_path: Path,
        *,
        model_sha: str = "model-sha",
    ) -> dict:
        return {
            "tracker": {
                "tracker_type": "pose",
                "model_sha256": "tracker-sha",
                "conf": 0.5,
            },
            "auxiliary_model": {"model_sha256": model_sha, "conf": 0.5},
            "dataset": {
                "recordings_manifest_sha256": generate_segments._sha256_file(
                    manifest_path
                ),
                "annotations_sha256": generate_segments._sha256_file(annotations_path),
            },
        }

    def test_rejects_model_sha_mismatch(self, tmp_path):
        manifest_path = tmp_path / "manifest.csv"
        manifest_path.write_text("x", encoding="utf-8")
        annotations_path = tmp_path / "annotations.csv"
        annotations_path.write_text("y", encoding="utf-8")
        selected_path = tmp_path / "selected.json"
        self._write_selected_profile(
            selected_path,
            manifest_sha=generate_segments._sha256_file(manifest_path),
            annotations_sha=generate_segments._sha256_file(annotations_path),
        )
        cache_dir = tmp_path
        (cache_dir / "manifest.json").write_text(
            json.dumps(
                self._cache_manifest(
                    manifest_path, annotations_path, model_sha="wrong-sha"
                )
            ),
            encoding="utf-8",
        )

        with pytest.raises(ValueError, match="auxiliary model SHA-256"):
            generate_segments.verify_cache_integrity(
                cache_dir=cache_dir,
                manifest_path=manifest_path,
                annotations_path=annotations_path,
                selected_profile_path=selected_path,
                manifest_by_video={},
                annotation_by_video={},
                video_ids=[],
            )

    def test_rejects_stale_annotations_file(self, tmp_path):
        manifest_path = tmp_path / "manifest.csv"
        manifest_path.write_text("x", encoding="utf-8")
        annotations_path = tmp_path / "annotations.csv"
        annotations_path.write_text("y", encoding="utf-8")
        selected_path = tmp_path / "selected.json"
        self._write_selected_profile(
            selected_path,
            manifest_sha=generate_segments._sha256_file(manifest_path),
            annotations_sha="stale-sha-not-matching-current-file",
        )
        cache_dir = tmp_path
        (cache_dir / "manifest.json").write_text(
            json.dumps(self._cache_manifest(manifest_path, annotations_path)),
            encoding="utf-8",
        )

        with pytest.raises(ValueError, match="annotations.csv의 SHA-256"):
            generate_segments.verify_cache_integrity(
                cache_dir=cache_dir,
                manifest_path=manifest_path,
                annotations_path=annotations_path,
                selected_profile_path=selected_path,
                manifest_by_video={},
                annotation_by_video={},
                video_ids=[],
            )

    def test_rejects_video_not_reviewed(self, tmp_path):
        manifest_path = tmp_path / "manifest.csv"
        manifest_path.write_text("x", encoding="utf-8")
        annotations_path = tmp_path / "annotations.csv"
        annotations_path.write_text("y", encoding="utf-8")
        selected_path = tmp_path / "selected.json"
        self._write_selected_profile(
            selected_path,
            manifest_sha=generate_segments._sha256_file(manifest_path),
            annotations_sha=generate_segments._sha256_file(annotations_path),
        )
        cache_dir = tmp_path
        (cache_dir / "manifest.json").write_text(
            json.dumps(self._cache_manifest(manifest_path, annotations_path)),
            encoding="utf-8",
        )
        video_id = "P4_S01_A01_contact_fall_01_cam01"
        (cache_dir / f"{video_id}.json").write_text(
            json.dumps(_cache_video([[1]], frame_count=300)), encoding="utf-8"
        )

        with pytest.raises(ValueError, match="reviewed"):
            generate_segments.verify_cache_integrity(
                cache_dir=cache_dir,
                manifest_path=manifest_path,
                annotations_path=annotations_path,
                selected_profile_path=selected_path,
                manifest_by_video={video_id: _manifest_row(frame_count="300")},
                annotation_by_video={video_id: {"review_status": "pending"}},
                video_ids=[video_id],
            )

    def test_rejects_frame_count_mismatch(self, tmp_path):
        manifest_path = tmp_path / "manifest.csv"
        manifest_path.write_text("x", encoding="utf-8")
        annotations_path = tmp_path / "annotations.csv"
        annotations_path.write_text("y", encoding="utf-8")
        selected_path = tmp_path / "selected.json"
        self._write_selected_profile(
            selected_path,
            manifest_sha=generate_segments._sha256_file(manifest_path),
            annotations_sha=generate_segments._sha256_file(annotations_path),
        )
        cache_dir = tmp_path
        (cache_dir / "manifest.json").write_text(
            json.dumps(self._cache_manifest(manifest_path, annotations_path)),
            encoding="utf-8",
        )
        video_id = "P4_S01_A01_contact_fall_01_cam01"
        (cache_dir / f"{video_id}.json").write_text(
            json.dumps(_cache_video([[1]], frame_count=250)), encoding="utf-8"
        )

        with pytest.raises(ValueError, match="frame_count"):
            generate_segments.verify_cache_integrity(
                cache_dir=cache_dir,
                manifest_path=manifest_path,
                annotations_path=annotations_path,
                selected_profile_path=selected_path,
                manifest_by_video={video_id: _manifest_row(frame_count="300")},
                annotation_by_video={video_id: {"review_status": "reviewed"}},
                video_ids=[video_id],
            )

    def test_accepts_consistent_cache(self, tmp_path):
        manifest_path = tmp_path / "manifest.csv"
        manifest_path.write_text("x", encoding="utf-8")
        annotations_path = tmp_path / "annotations.csv"
        annotations_path.write_text("y", encoding="utf-8")
        selected_path = tmp_path / "selected.json"
        self._write_selected_profile(
            selected_path,
            manifest_sha=generate_segments._sha256_file(manifest_path),
            annotations_sha=generate_segments._sha256_file(annotations_path),
        )
        cache_dir = tmp_path
        (cache_dir / "manifest.json").write_text(
            json.dumps(self._cache_manifest(manifest_path, annotations_path)),
            encoding="utf-8",
        )
        video_id = "P4_S01_A01_contact_fall_01_cam01"
        (cache_dir / f"{video_id}.json").write_text(
            json.dumps(_cache_video([[1]], frame_count=300)), encoding="utf-8"
        )

        generate_segments.verify_cache_integrity(
            cache_dir=cache_dir,
            manifest_path=manifest_path,
            annotations_path=annotations_path,
            selected_profile_path=selected_path,
            manifest_by_video={video_id: _manifest_row(frame_count="300")},
            annotation_by_video={video_id: {"review_status": "reviewed"}},
            video_ids=[video_id],
        )
