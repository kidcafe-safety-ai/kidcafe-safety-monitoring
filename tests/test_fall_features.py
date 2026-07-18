"""FallFeatureExtractor 단위 테스트."""

from __future__ import annotations

import pytest

from src.safety.fall_features import FallFeatureExtractor
from src.safety.multi_track_history import TrackSample

_HORIZONTAL_THRESHOLD = 1.3


def _sample(time_sec, bbox, foot_point=None, confidence=0.9, frame_number=0):
    x1, y1, x2, y2 = bbox
    foot_point = foot_point or ((x1 + x2) / 2.0, y2)
    return TrackSample(
        frame_number=frame_number,
        time_sec=time_sec,
        bbox=tuple(bbox),
        foot_point=tuple(foot_point),
        confidence=confidence,
    )


class TestInsufficientHistory:
    def test_returns_none_with_fewer_than_two_samples(self):
        extractor = FallFeatureExtractor()
        assert extractor.extract([], _HORIZONTAL_THRESHOLD) is None
        assert (
            extractor.extract([_sample(0.0, [0, 0, 20, 60])], _HORIZONTAL_THRESHOLD) is None
        )

    def test_returns_none_when_zero_time_elapsed(self):
        extractor = FallFeatureExtractor()
        history = [
            _sample(1.0, [0, 0, 20, 60]),
            _sample(1.0, [0, 0, 20, 60]),
        ]
        assert extractor.extract(history, _HORIZONTAL_THRESHOLD) is None


class TestStandingStillFeatures:
    def test_no_movement_yields_zero_velocity_and_normal_posture(self):
        extractor = FallFeatureExtractor()
        bbox = [40.0, 20.0, 60.0, 80.0]  # width=20, height=60 → aspect_ratio=0.33
        history = [
            _sample(0.0, bbox, frame_number=0),
            _sample(0.5, bbox, frame_number=5),
        ]

        features = extractor.extract(history, _HORIZONTAL_THRESHOLD)

        assert features is not None
        assert features.aspect_ratio == pytest.approx(20.0 / 60.0)
        assert features.center_vertical_velocity == pytest.approx(0.0)
        assert features.foot_point_vertical_velocity == pytest.approx(0.0)
        assert features.height_change_rate == pytest.approx(0.0)
        assert features.is_horizontal_posture is False
        assert features.track_age_sec == pytest.approx(0.5)


class TestFallingFeatures:
    def test_rapid_descent_and_horizontal_posture_detected(self):
        extractor = FallFeatureExtractor()
        # 서 있는 자세(height=60) → 누운 자세(height=20, width=60)로 0.5초 만에 변화
        history = [
            _sample(0.0, [40.0, 0.0, 60.0, 60.0], frame_number=0),
            _sample(0.5, [20.0, 60.0, 80.0, 80.0], frame_number=5),
        ]

        features = extractor.extract(history, _HORIZONTAL_THRESHOLD)

        assert features is not None
        assert features.aspect_ratio == pytest.approx(60.0 / 20.0)
        assert features.is_horizontal_posture is True
        assert features.height_change_rate < 0  # 높이가 줄어듦
        assert features.center_vertical_velocity > 0  # 중심이 아래로 이동


class TestAverageConfidence:
    def test_average_confidence_over_history(self):
        extractor = FallFeatureExtractor()
        history = [
            _sample(0.0, [0, 0, 20, 60], confidence=0.8, frame_number=0),
            _sample(0.2, [0, 0, 20, 60], confidence=0.6, frame_number=2),
            _sample(0.4, [0, 0, 20, 60], confidence=1.0, frame_number=4),
        ]

        features = extractor.extract(history, _HORIZONTAL_THRESHOLD)

        assert features.avg_confidence == pytest.approx((0.8 + 0.6 + 1.0) / 3)


class TestZeroHeightGuard:
    def test_returns_none_when_latest_height_is_zero(self):
        extractor = FallFeatureExtractor()
        history = [
            _sample(0.0, [0, 0, 20, 60]),
            _sample(0.5, [0, 60, 20, 60]),  # y1 == y2 → height 0
        ]
        assert extractor.extract(history, _HORIZONTAL_THRESHOLD) is None
