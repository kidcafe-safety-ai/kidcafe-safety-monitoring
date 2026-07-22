"""scripts/evaluate_fall_from_cache.py의 순수 검증 로직 테스트.

_validate_cache_metadata()는 cv2/YOLO 없이 dict/Path만으로 검증 가능하다.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import evaluate_fall as ef  # noqa: E402
import evaluate_fall_from_cache as efc  # noqa: E402

from src.common.types import Track, TrackingResult  # noqa: E402
from src.safety.auxiliary_fall_model import FallDetection  # noqa: E402
from src.safety.fall_detector import FallDetectorConfig  # noqa: E402
from src.safety.fall_model_matching import match_detections_to_tracks  # noqa: E402
from src.safety.fall_pipeline import FallPipeline  # noqa: E402

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


def _tracking_result(frame_number, track_id=1) -> TrackingResult:
    return TrackingResult(
        frame_number=frame_number,
        timestamp="00:00:00.000",
        video_source="video",
        tracks=[
            Track(
                track_id=track_id,
                bbox=[0.0, 0.0, 100.0, 200.0],
                foot_point=[50.0, 200.0],
                confidence=0.9,
            )
        ],
    )


def test_cached_adaptive_cadence_holds_evidence_and_refreshes_on_interval():
    cadence = efc.CachedAdaptiveAuxiliaryCadence(
        interval_frames=3, iou_threshold=0.3
    )
    fall = [
        FallDetection(
            bbox=[0.0, 0.0, 100.0, 200.0],
            label="fall",
            confidence=0.9,
        )
    ]

    first, first_inferred = cadence.resolve(
        _tracking_result(0), fall, fall, use_auxiliary=True
    )
    held, held_inferred = cadence.resolve(
        _tracking_result(1), [], fall, use_auxiliary=True
    )
    refreshed, refreshed_inferred = cadence.resolve(
        _tracking_result(3), fall, fall, use_auxiliary=True
    )

    assert first is fall
    assert first_inferred is True
    assert [detection.label for detection in held] == ["fall"]
    assert held_inferred is False
    assert refreshed is fall
    assert refreshed_inferred is True


def test_runtime_and_cache_replay_match_across_fallback_hold_and_new_track():
    """Runtime과 cache replay가 복합 adaptive cadence에서도 같은 Event를 만든다."""

    class StubAuxiliaryModel:
        enabled = True

        def __init__(self, detections_by_call):
            self._detections_by_call = iter(detections_by_call)
            self.infer_calls = 0

        def infer(self, _frame):
            self.infer_calls += 1
            return next(self._detections_by_call)

    track_one = [0.0, 0.0, 100.0, 200.0]
    track_two = [120.0, 0.0, 220.0, 200.0]
    fall_one = FallDetection(bbox=track_one, label="fall", confidence=0.9)
    fall_both = [
        fall_one,
        FallDetection(bbox=track_two, label="fall", confidence=0.9),
    ]
    tracking_results = [
        _tracking_result(0),
        _tracking_result(1),
        _tracking_result(2),
        TrackingResult(
            frame_number=3,
            timestamp="00:00:00.300",
            video_source="video",
            tracks=[
                _tracking_result(3).tracks[0],
                Track(
                    track_id=2,
                    bbox=track_two,
                    foot_point=[170.0, 200.0],
                    confidence=0.9,
                ),
            ],
        ),
        TrackingResult(
            frame_number=4,
            timestamp="00:00:00.400",
            video_source="video",
            tracks=[
                _tracking_result(4).tracks[0],
                Track(
                    track_id=2,
                    bbox=track_two,
                    foot_point=[170.0, 200.0],
                    confidence=0.9,
                ),
            ],
        ),
    ]
    use_auxiliary = [False, True, True, True, True]
    raw_detections = [[], [fall_one], [fall_one], fall_both, fall_both]
    config = FallDetectorConfig(
        min_track_age_sec=0.1,
        model_candidate_entry_sec=0.05,
        model_confirm_sec=0.25,
        model_vote_window_sec=0.5,
    )

    runtime_model = StubAuxiliaryModel([[fall_one], fall_both])
    runtime_gate = MagicMock()
    runtime_gate.evaluate.side_effect = [
        SimpleNamespace(use_auxiliary=value) for value in use_auxiliary
    ]
    runtime_pipeline = FallPipeline(
        fps=10.0,
        detector_config=config,
        auxiliary_model=runtime_model,
        auxiliary_inference_interval_frames=3,
        pose_normal_gate=runtime_gate,
    )
    runtime_events = []
    runtime_diagnostics = []
    for tracking_result in tracking_results:
        runtime_events.extend(
            runtime_pipeline.process(
                np.zeros((8, 8, 3), dtype=np.uint8),
                tracking_result,
                diagnostics=runtime_diagnostics,
            )
        )

    replay_pipeline = FallPipeline(fps=10.0, detector_config=config)
    replay_cadence = efc.CachedAdaptiveAuxiliaryCadence(
        interval_frames=3, iou_threshold=0.3
    )
    replay_events = []
    replay_diagnostics = []
    replay_inference_frames = []
    for tracking_result, use_aux, raw in zip(
        tracking_results, use_auxiliary, raw_detections
    ):
        selected = raw if use_aux else efc._normal_detections(tracking_result)
        detections, inferred = replay_cadence.resolve(
            tracking_result, selected, raw, use_auxiliary=use_aux
        )
        if inferred:
            replay_inference_frames.append(tracking_result.frame_number)
        evidence = {
            item.track_id: item
            for item in match_detections_to_tracks(
                tracking_result.tracks, detections, iou_threshold=0.3
            )
        }
        replay_events.extend(
            replay_pipeline.process_with_evidence(
                tracking_result, evidence, diagnostics=replay_diagnostics
            )
        )

    assert runtime_model.infer_calls == 2
    assert replay_inference_frames == [1, 3]
    assert [event.frame_number for event in runtime_events] == [4]
    assert [event.frame_number for event in replay_events] == [4]
    assert runtime_diagnostics[0]["confirm_path"] == "model"
    assert replay_diagnostics[0]["confirm_path"] == "model"
