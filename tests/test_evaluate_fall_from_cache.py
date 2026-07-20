"""scripts/evaluate_fall_from_cache.py의 순수 검증 로직 테스트.

_validate_cache_metadata()는 cv2/YOLO 없이 dict/Path만으로 검증 가능하다.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import evaluate_fall as ef  # noqa: E402
import evaluate_fall_from_cache as efc  # noqa: E402

_TRACKER_META = {
    "tracker_type": "pose",
    "model_path": "yolo26n-pose.pt",
    "model_sha256": "abc",
    "conf": 0.5,
    "tracker_config": "bytetrack.yaml",
    "tracker_config_sha256": None,
}


def _row(**overrides) -> ef._AnnotationRow:
    defaults = dict(
        video_id="v1",
        label="no_fall",
        video_path="v1.avi",
        fall_start_frame=None,
        impact_frame=None,
        lying_start_frame=None,
        review_status="reviewed",
    )
    defaults.update(overrides)
    return ef._AnnotationRow(**defaults)


def _manifest(**overrides) -> dict:
    defaults = dict(
        cache_schema_version=1,
        split="development",
        videos_dir="/data/development",
        tracker=_TRACKER_META,
        auxiliary_model=None,
    )
    defaults.update(overrides)
    return defaults


def _metadata(**overrides) -> dict:
    defaults = dict(
        cache_schema_version=1,
        video_id="v1",
        video_path="/data/development/v1.avi",
        video_size_bytes=None,
        fps=20.0,
        frame_count=1,
        tracker=_TRACKER_META,
        auxiliary_model=None,
    )
    defaults.update(overrides)
    return defaults


class TestValidateCacheMetadata:
    def test_matching_metadata_returns_none(self):
        row = _row()
        manifest = _manifest()
        metadata = _metadata()

        result = efc._validate_cache_metadata(metadata, manifest, row, Path("/data/development"))

        assert result is None

    def test_tracker_mismatch_is_rejected(self):
        row = _row()
        manifest = _manifest()
        metadata = _metadata(tracker={**_TRACKER_META, "conf": 0.99})

        result = efc._validate_cache_metadata(metadata, manifest, row, Path("/data/development"))

        assert result is not None
        assert "tracker" in result

    def test_auxiliary_model_mismatch_is_rejected(self):
        row = _row()
        manifest = _manifest(auxiliary_model=None)
        metadata = _metadata(
            auxiliary_model={"model_path": "fall_detector_v1.pt", "model_sha256": "x", "conf": 0.5}
        )

        result = efc._validate_cache_metadata(metadata, manifest, row, Path("/data/development"))

        assert result is not None
        assert "auxiliary_model" in result

    def test_video_path_mismatch_is_rejected(self):
        row = _row()
        manifest = _manifest()
        metadata = _metadata(video_path="/data/development/some_other_video.avi")

        result = efc._validate_cache_metadata(metadata, manifest, row, Path("/data/development"))

        assert result is not None
        assert "video_path" in result

    def test_video_path_none_is_not_rejected(self):
        """video_path를 기록하지 않은(구버전) 캐시는 이 검증을 그냥 통과시킨다."""
        row = _row()
        manifest = _manifest()
        metadata = _metadata(video_path=None)

        result = efc._validate_cache_metadata(metadata, manifest, row, Path("/data/development"))

        assert result is None

    def test_video_size_mismatch_is_rejected(self, tmp_path):
        video_file = tmp_path / "v1.avi"
        video_file.write_bytes(b"x" * 100)
        row = _row(video_path="v1.avi")
        manifest = _manifest(videos_dir=str(tmp_path))
        metadata = _metadata(video_path=str(video_file), video_size_bytes=999)

        result = efc._validate_cache_metadata(metadata, manifest, row, tmp_path)

        assert result is not None
        assert "크기" in result

    def test_video_size_match_is_not_rejected(self, tmp_path):
        video_file = tmp_path / "v1.avi"
        video_file.write_bytes(b"x" * 100)
        row = _row(video_path="v1.avi")
        manifest = _manifest(videos_dir=str(tmp_path))
        metadata = _metadata(video_path=str(video_file), video_size_bytes=100)

        result = efc._validate_cache_metadata(metadata, manifest, row, tmp_path)

        assert result is None
