"""메모리 frame source와 캐시 저장->로드 frame source가 완전히 같은 채점

결과를 내는지 확인하는 회귀 테스트.

실제 YOLO/cv2 없이 합성 Track/FallDetection 시퀀스로 다중 프레임 낙상
시나리오를 만들고, 같은 시퀀스를 (1) 메모리에서 바로 score_video_from_frame_source()에
넘긴 결과와 (2) fall_signal_cache로 저장했다가 다시 읽어 넘긴 결과를
video_result_to_dict()로 완전히 비교한다.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import evaluate_fall as ef  # noqa: E402
import fall_signal_cache as cache  # noqa: E402

from src.common.types import Track, TrackingResult  # noqa: E402
from src.safety.auxiliary_fall_model import FallDetection  # noqa: E402
from src.safety.fall_detector import FallDetectorConfig  # noqa: E402

_STANDING_BBOX = [40.0, 0.0, 60.0, 60.0]
_LYING_BBOX = [10.0, 50.0, 90.0, 70.0]
_FPS = 10.0


def _row(**overrides) -> ef._AnnotationRow:
    defaults = dict(
        video_id="v1",
        label="fall",
        video_path="v1.avi",
        fall_start_frame=5,
        impact_frame=8,
        lying_start_frame=10,
        review_status="reviewed",
    )
    defaults.update(overrides)
    return ef._AnnotationRow(**defaults)


def _fast_config(**overrides) -> FallDetectorConfig:
    cfg = FallDetectorConfig(cooldown_sec=1.0)
    for key, value in overrides.items():
        setattr(cfg, key, value)
    return cfg


def _track(bbox, foot_point, track_id=1) -> Track:
    return Track(track_id=track_id, bbox=list(bbox), foot_point=list(foot_point), confidence=0.9)


def _bbox_confirm_frames():
    """정지 5프레임 + 급격한 낙상(눕는 자세) 6프레임 -> bbox 경로로 confirm."""
    frames = []
    for i in range(5):
        frames.append((i, [_track(_STANDING_BBOX, [50.0, 60.0])], None))
    for i in range(5, 11):
        frames.append((i, [_track(_LYING_BBOX, [50.0, 70.0])], None))
    return frames


def _in_memory_frame_source(frames):
    for frame_number, tracks, raw_detections in frames:
        tracking_result = TrackingResult(
            frame_number=frame_number,
            timestamp=f"00:00:{frame_number / _FPS:06.3f}",
            video_source="v1",
            tracks=tracks,
        )
        yield frame_number, tracking_result, raw_detections


def _cache_round_trip_frame_source(frames, tmp_path):
    cached_frames = [
        cache.CachedFrame(
            frame_number=frame_number,
            timestamp=f"00:00:{frame_number / _FPS:06.3f}",
            tracks=tracks,
            raw_detections=raw_detections,
        )
        for frame_number, tracks, raw_detections in frames
    ]
    path = tmp_path / "v1.json"
    cache.write_video_cache(
        path, video_id="v1", fps=_FPS, tracker_meta={}, auxiliary_meta=None, frames=cached_frames
    )
    _metadata, loaded_frames = cache.read_video_cache(path, expected_video_id="v1")

    for cached_frame in loaded_frames:
        tracking_result = TrackingResult(
            frame_number=cached_frame.frame_number,
            timestamp=cached_frame.timestamp,
            video_source="v1",
            tracks=cached_frame.tracks,
        )
        yield cached_frame.frame_number, tracking_result, cached_frame.raw_detections


class TestInMemoryVsCacheRoundTripEquivalence:
    def test_bbox_confirmed_fall_produces_identical_video_result(self, tmp_path):
        frames = _bbox_confirm_frames()
        row = _row()
        config = _fast_config()

        result_memory = ef.score_video_from_frame_source(
            row, _in_memory_frame_source(frames), _FPS, config
        )
        result_cache = ef.score_video_from_frame_source(
            row, _cache_round_trip_frame_source(frames, tmp_path), _FPS, config
        )

        assert ef.video_result_to_dict(result_memory) == ef.video_result_to_dict(result_cache)
        # 실제로 이벤트가 나온 시나리오인지도 확인 — 둘 다 빈 결과라서
        # 우연히 같아 보이는 걸 막는다.
        assert result_memory.event_frames != []

    def test_no_event_scenario_also_matches(self, tmp_path):
        """계속 서 있기만 하는(이벤트 없는) 시나리오도 동일해야 한다."""
        frames = [(i, [_track(_STANDING_BBOX, [50.0, 60.0])], None) for i in range(8)]
        row = _row(
            label="no_fall", fall_start_frame=None, impact_frame=None, lying_start_frame=None
        )
        config = _fast_config()

        result_memory = ef.score_video_from_frame_source(
            row, _in_memory_frame_source(frames), _FPS, config
        )
        result_cache = ef.score_video_from_frame_source(
            row, _cache_round_trip_frame_source(frames, tmp_path), _FPS, config
        )

        assert ef.video_result_to_dict(result_memory) == ef.video_result_to_dict(result_cache)
        assert result_memory.event_frames == []

    def test_model_only_scenario_with_raw_detections_matches(self, tmp_path):
        """보조 모델 raw detection이 있는 프레임(캐시의 핵심 사용 사례)도 동일해야 한다."""
        frames = []
        for i in range(5):
            frames.append((i, [_track(_STANDING_BBOX, [50.0, 60.0])], []))
        for i in range(5, 8):
            frames.append(
                (
                    i,
                    [_track(_STANDING_BBOX, [50.0, 60.0])],
                    [FallDetection(bbox=list(_STANDING_BBOX), label="fall", confidence=0.9)],
                )
            )
        row = _row()
        config = _fast_config()

        result_memory = ef.score_video_from_frame_source(
            row, _in_memory_frame_source(frames), _FPS, config, fall_model_iou_threshold=0.3
        )
        result_cache = ef.score_video_from_frame_source(
            row,
            _cache_round_trip_frame_source(frames, tmp_path),
            _FPS,
            config,
            fall_model_iou_threshold=0.3,
        )

        assert ef.video_result_to_dict(result_memory) == ef.video_result_to_dict(result_cache)
        assert result_memory.event_frames != []
        assert result_memory.confirm_path == "model"

    def test_sample_and_hold_interval_matches_cache_round_trip(self, tmp_path):
        """간격 추론의 Track별 sample-and-hold도 캐시 재생과 동일해야 한다."""
        frames = []
        for i in range(5):
            frames.append((i, [_track(_STANDING_BBOX, [50.0, 60.0])], []))
        for i in range(5, 9):
            frames.append(
                (
                    i,
                    [_track(_STANDING_BBOX, [50.0, 60.0])],
                    [FallDetection(bbox=list(_STANDING_BBOX), label="fall", confidence=0.9)],
                )
            )
        row = _row()
        config = _fast_config()

        result_memory = ef.score_video_from_frame_source(
            row,
            _in_memory_frame_source(frames),
            _FPS,
            config,
            fall_model_iou_threshold=0.3,
            fall_model_interval_frames=2,
        )
        result_cache = ef.score_video_from_frame_source(
            row,
            _cache_round_trip_frame_source(frames, tmp_path),
            _FPS,
            config,
            fall_model_iou_threshold=0.3,
            fall_model_interval_frames=2,
        )

        assert ef.video_result_to_dict(result_memory) == ef.video_result_to_dict(result_cache)
        assert result_memory.event_frames != []
        assert result_memory.confirm_path == "model"


class TestIouThresholdSweepChangesReplayResult:
    def test_lower_iou_threshold_matches_partial_overlap_higher_does_not(self, tmp_path):
        """캐시 재생의 핵심 가치: iou_threshold만 바꿔도 매칭 결과가 달라져야 한다."""
        # Track bbox와 절반만 겹치는 detection -> IoU ~= 1/3
        track_bbox = [0.0, 0.0, 10.0, 10.0]
        overlapping_detection_bbox = [5.0, 0.0, 15.0, 10.0]

        frames = []
        for i in range(5):
            frames.append((i, [_track(track_bbox, [5.0, 10.0])], []))
        for i in range(5, 8):
            frames.append(
                (
                    i,
                    [_track(track_bbox, [5.0, 10.0])],
                    [FallDetection(bbox=overlapping_detection_bbox, label="fall", confidence=0.9)],
                )
            )
        row = _row()
        config = _fast_config()

        result_low = ef.score_video_from_frame_source(
            row, _cache_round_trip_frame_source(frames, tmp_path), _FPS, config,
            fall_model_iou_threshold=0.2,
        )
        result_high = ef.score_video_from_frame_source(
            row, _cache_round_trip_frame_source(frames, tmp_path), _FPS, config,
            fall_model_iou_threshold=0.9,
        )

        assert result_low.confirm_path == "model"  # IoU(~0.33) >= 0.2 -> 매칭됨
        assert result_high.confirm_path is None  # IoU(~0.33) < 0.9 -> 매칭 실패, dynamic 근거도 없음
        assert result_low.event_frames != result_high.event_frames


class TestNoFallWholeVideoTrackDiagnostics:
    """Tracker Sweep이 정상 영상의 false Track 증가를

    비교하려면 no_fall 행에도 track_coverage/id_switch_count가 필요하다 —
    onset이 없어 timely 구간을 못 만드니 영상 전체를 구간으로 쓴다.
    """

    def test_no_fall_row_gets_whole_video_track_diagnostics(self):
        row = _row(
            label="no_fall", fall_start_frame=None, impact_frame=None, lying_start_frame=None
        )
        frames = [(i, [_track(_STANDING_BBOX, [50.0, 60.0])], None) for i in range(8)]

        result = ef.score_video_from_frame_source(
            row, _in_memory_frame_source(frames), _FPS, _fast_config()
        )

        assert result.track_coverage == pytest.approx(1.0)
        assert result.id_switch_count == 0

    def test_no_fall_row_id_switch_detected(self):
        row = _row(
            label="no_fall", fall_start_frame=None, impact_frame=None, lying_start_frame=None
        )
        frames = []
        for i in range(4):
            frames.append((i, [_track(_STANDING_BBOX, [50.0, 60.0], track_id=1)], None))
        for i in range(4, 8):
            frames.append((i, [_track(_STANDING_BBOX, [50.0, 60.0], track_id=2)], None))

        result = ef.score_video_from_frame_source(
            row, _in_memory_frame_source(frames), _FPS, _fast_config()
        )

        assert result.id_switch_count == 1

    def test_no_fall_row_no_tracks_at_all_leaves_diagnostics_none(self):
        """Track 자체가 한 번도 없으면(빈 tracks_by_frame) fall 행과 마찬가지로

        window_frame_count=0 케이스와 동일하게 None으로 남아야 한다.
        """
        row = _row(
            label="no_fall", fall_start_frame=None, impact_frame=None, lying_start_frame=None
        )
        frames = [(i, [], None) for i in range(5)]

        result = ef.score_video_from_frame_source(
            row, _in_memory_frame_source(frames), _FPS, _fast_config()
        )

        # tracks_by_frame 자체는 채워지지만(빈 리스트씩), 매 프레임 no-track이므로
        # track_coverage는 0.0(0으로 나눠지지 않음)이어야 한다.
        assert result.track_coverage == pytest.approx(0.0)


class TestScoreVideoFromFrameSourceValidation:
    def test_rejects_invalid_iou_threshold_even_without_auxiliary_model(self):
        """보조 모델을 안 써서 raw_detections가 매 프레임 None이어도 iou_threshold는

        즉시 검증해야 한다. raw_detections가 있는 프레임에서만 검증하면 이
        값이 끝까지 확인되지 않는다.
        """
        row = _row(
            label="no_fall", fall_start_frame=None, impact_frame=None, lying_start_frame=None
        )
        frames = [(0, [], None)]

        with pytest.raises(ValueError, match="fall_model_iou_threshold"):
            ef.score_video_from_frame_source(
                row, _in_memory_frame_source(frames), _FPS, _fast_config(),
                fall_model_iou_threshold=1.5,
            )
