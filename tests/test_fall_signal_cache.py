"""scripts/fall_signal_cache.py 테스트.

실제 YOLO 추론 없이, Track/FallDetection 객체를 직접 만들어 저장->로드
round-trip과 스키마 버전 검증만 확인한다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import fall_signal_cache as cache  # noqa: E402

from src.common.types import Track  # noqa: E402
from src.safety.auxiliary_fall_model import FallDetection  # noqa: E402


def _track(track_id=1, with_pose=False) -> Track:
    return Track(
        track_id=track_id,
        bbox=[10.0, 20.0, 30.0, 60.0],
        foot_point=[20.0, 60.0],
        confidence=0.85,
        keypoints=[[1.0, 2.0]] * 17 if with_pose else None,
        keypoints_conf=[0.7] * 17 if with_pose else None,
    )


class TestSha256File:
    def test_returns_none_for_missing_or_non_local_path(self):
        assert cache.sha256_file("bytetrack.yaml") is None
        assert cache.sha256_file("/no/such/file/at/all.pt") is None

    def test_returns_stable_hash_for_real_file(self, tmp_path):
        target = tmp_path / "weights.pt"
        target.write_bytes(b"fake model bytes")

        first = cache.sha256_file(str(target))
        second = cache.sha256_file(str(target))

        assert first is not None
        assert first == second

    def test_different_content_yields_different_hash(self, tmp_path):
        a = tmp_path / "a.pt"
        b = tmp_path / "b.pt"
        a.write_bytes(b"content a")
        b.write_bytes(b"content b")

        assert cache.sha256_file(str(a)) != cache.sha256_file(str(b))


class TestWriteReadRoundTrip:
    def test_round_trips_tracks_and_raw_detections(self, tmp_path):
        frames = [
            cache.CachedFrame(
                frame_number=0,
                timestamp="00:00:00.000",
                tracks=[_track(1, with_pose=True)],
                raw_detections=[
                    FallDetection(bbox=[1.0, 2.0, 3.0, 4.0], label="fall", confidence=0.9)
                ],
            ),
            cache.CachedFrame(
                frame_number=1,
                timestamp="00:00:00.050",
                tracks=[],
                raw_detections=[],
            ),
        ]
        path = tmp_path / "S1_fall_backwards.json"

        cache.write_video_cache(
            path,
            video_id="S1_fall_backwards",
            fps=20.0,
            tracker_meta={"model_path": "yolo26n-pose.pt", "model_sha256": None, "conf": 0.5},
            auxiliary_meta={
                "model_path": "fall_detector_v1.pt", "model_sha256": None, "conf": 0.5
            },
            frames=frames,
        )
        metadata, loaded_frames = cache.read_video_cache(path)

        assert metadata["video_id"] == "S1_fall_backwards"
        assert metadata["fps"] == 20.0
        assert metadata["frame_count"] == 2
        assert metadata["cache_schema_version"] == cache.CACHE_SCHEMA_VERSION
        assert "frames" not in metadata

        assert len(loaded_frames) == 2
        assert loaded_frames[0].tracks[0].track_id == 1
        assert loaded_frames[0].tracks[0].keypoints == [[1.0, 2.0]] * 17
        assert loaded_frames[0].raw_detections[0].label == "fall"
        assert loaded_frames[1].tracks == []
        assert loaded_frames[1].raw_detections == []

    def test_none_raw_detections_round_trips_as_none(self, tmp_path):
        """보조 모델을 안 쓴 캐시는 raw_detections가 None이어야 한다(빈 리스트와 다른 의미)."""
        frames = [
            cache.CachedFrame(
                frame_number=0, timestamp="00:00:00.000", tracks=[_track()], raw_detections=None
            ),
        ]
        path = tmp_path / "no_aux.json"

        cache.write_video_cache(
            path,
            video_id="v1",
            fps=10.0,
            tracker_meta={"model_path": "yolo26n-pose.pt", "model_sha256": None, "conf": 0.5},
            auxiliary_meta=None,
            frames=frames,
        )
        metadata, loaded_frames = cache.read_video_cache(path)

        assert metadata["auxiliary_model"] is None
        assert loaded_frames[0].raw_detections is None

    def test_write_is_atomic_no_partial_file_on_success(self, tmp_path):
        path = tmp_path / "v1.json"
        cache.write_video_cache(
            path,
            video_id="v1",
            fps=10.0,
            tracker_meta={},
            auxiliary_meta=None,
            frames=[cache.CachedFrame(0, "00:00:00.000", [], None)],
        )
        assert path.exists()
        assert not path.with_suffix(".json.tmp").exists()

    def test_records_video_path_when_given(self, tmp_path):
        path = tmp_path / "v1.json"
        cache.write_video_cache(
            path,
            video_id="v1",
            fps=10.0,
            tracker_meta={},
            auxiliary_meta=None,
            frames=[cache.CachedFrame(0, "00:00:00.000", [], None)],
            video_path="/data/Subject.1/Fall backwards/x.avi",
        )
        metadata, _ = cache.read_video_cache(path)
        assert metadata["video_path"] == "/data/Subject.1/Fall backwards/x.avi"

    def test_rejects_unsupported_schema_version(self, tmp_path):
        path = tmp_path / "old.json"
        path.write_text(
            json.dumps(
                {
                    "cache_schema_version": 999,
                    "video_id": "v1",
                    "fps": 10.0,
                    "frame_count": 0,
                    "tracker": {},
                    "auxiliary_model": None,
                    "frames": [],
                }
            )
        )

        with pytest.raises(ValueError, match="cache_schema_version"):
            cache.read_video_cache(path)


class TestWriteVideoCacheValidation:
    def test_rejects_non_positive_fps(self, tmp_path):
        with pytest.raises(ValueError, match="fps"):
            cache.write_video_cache(
                tmp_path / "v1.json",
                video_id="v1",
                fps=0.0,
                tracker_meta={},
                auxiliary_meta=None,
                frames=[cache.CachedFrame(0, "00:00:00.000", [], None)],
            )

    def test_rejects_empty_frames(self, tmp_path):
        with pytest.raises(ValueError, match="frames"):
            cache.write_video_cache(
                tmp_path / "v1.json",
                video_id="v1",
                fps=10.0,
                tracker_meta={},
                auxiliary_meta=None,
                frames=[],
            )

    def test_rejects_non_sequential_frame_numbers(self, tmp_path):
        with pytest.raises(ValueError, match="frame_number"):
            cache.write_video_cache(
                tmp_path / "v1.json",
                video_id="v1",
                fps=10.0,
                tracker_meta={},
                auxiliary_meta=None,
                frames=[
                    cache.CachedFrame(0, "00:00:00.000", [], None),
                    cache.CachedFrame(2, "00:00:00.100", [], None),  # 1이 빠짐
                ],
            )


class TestReadVideoCacheValidation:
    def _write_minimal(self, path, **overrides):
        import json

        payload = {
            "cache_schema_version": cache.CACHE_SCHEMA_VERSION,
            "video_id": "v1",
            "video_path": None,
            "fps": 10.0,
            "frame_count": 1,
            "tracker": {},
            "auxiliary_model": None,
            "frames": [
                {
                    "frame_number": 0,
                    "timestamp": "00:00:00.000",
                    "tracks": [],
                    "raw_detections": None,
                }
            ],
        }
        payload.update(overrides)
        path.write_text(json.dumps(payload))

    def test_rejects_video_id_mismatch(self, tmp_path):
        path = tmp_path / "v1.json"
        self._write_minimal(path)

        with pytest.raises(ValueError, match="video_id"):
            cache.read_video_cache(path, expected_video_id="other_id")

    def test_accepts_matching_expected_video_id(self, tmp_path):
        path = tmp_path / "v1.json"
        self._write_minimal(path)

        metadata, frames = cache.read_video_cache(path, expected_video_id="v1")
        assert metadata["video_id"] == "v1"

    def test_rejects_non_positive_fps(self, tmp_path):
        path = tmp_path / "v1.json"
        self._write_minimal(path, fps=0.0)

        with pytest.raises(ValueError, match="fps"):
            cache.read_video_cache(path)

    def test_rejects_frame_count_mismatch(self, tmp_path):
        path = tmp_path / "v1.json"
        self._write_minimal(path, frame_count=5)  # 실제 frames는 1개

        with pytest.raises(ValueError, match="frame_count"):
            cache.read_video_cache(path)

    def test_rejects_empty_frames(self, tmp_path):
        path = tmp_path / "v1.json"
        self._write_minimal(path, frames=[], frame_count=0)

        with pytest.raises(ValueError, match="frames"):
            cache.read_video_cache(path)

    def test_rejects_non_sequential_frame_numbers(self, tmp_path):
        path = tmp_path / "v1.json"
        self._write_minimal(
            path,
            frame_count=2,
            frames=[
                {
                    "frame_number": 0,
                    "timestamp": "00:00:00.000",
                    "tracks": [],
                    "raw_detections": None,
                },
                {
                    "frame_number": 5,
                    "timestamp": "00:00:00.100",
                    "tracks": [],
                    "raw_detections": None,
                },
            ],
        )

        with pytest.raises(ValueError, match="frame_number"):
            cache.read_video_cache(path)


class TestManifest:
    def test_build_manifest_shape(self):
        manifest = cache.build_manifest(
            split="development",
            videos_dir="/data/development",
            tracker_meta={"model_path": "yolo26n-pose.pt", "conf": 0.5},
            auxiliary_meta=None,
        )
        assert manifest["split"] == "development"
        assert manifest["videos_dir"] == "/data/development"
        assert manifest["cache_schema_version"] == cache.CACHE_SCHEMA_VERSION

    def test_read_manifest_returns_none_when_missing(self, tmp_path):
        assert cache.read_manifest(tmp_path) is None

    def test_write_then_read_manifest_round_trips(self, tmp_path):
        manifest = cache.build_manifest(
            split="validation",
            videos_dir="/data/validation",
            tracker_meta={"model_path": "yolo26n-pose.pt", "conf": 0.5},
            auxiliary_meta={"model_path": "fall_detector_v1.pt", "conf": 0.5},
        )
        cache.write_manifest(tmp_path, manifest)

        loaded = cache.read_manifest(tmp_path)

        assert loaded == manifest


class TestCachePathFor:
    def test_builds_video_id_json_path(self, tmp_path):
        result = cache.cache_path_for(tmp_path, "S7_fall_backwards")
        assert result == tmp_path / "S7_fall_backwards.json"


class TestHasExistingVideoCaches:
    def test_false_for_nonexistent_dir(self, tmp_path):
        assert cache.has_existing_video_caches(tmp_path / "does_not_exist") is False

    def test_false_for_empty_dir(self, tmp_path):
        assert cache.has_existing_video_caches(tmp_path) is False

    def test_false_when_only_manifest_present(self, tmp_path):
        cache.write_manifest(
            tmp_path, cache.build_manifest("development", "/data", {}, None)
        )
        assert cache.has_existing_video_caches(tmp_path) is False

    def test_true_when_a_video_cache_file_present(self, tmp_path):
        (tmp_path / "S1_fall_backwards.json").write_text("{}")
        assert cache.has_existing_video_caches(tmp_path) is True

    def test_true_when_video_cache_present_alongside_manifest(self, tmp_path):
        cache.write_manifest(
            tmp_path, cache.build_manifest("development", "/data", {}, None)
        )
        (tmp_path / "S1_fall_backwards.json").write_text("{}")
        assert cache.has_existing_video_caches(tmp_path) is True
