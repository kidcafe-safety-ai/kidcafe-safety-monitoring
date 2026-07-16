"""FallDetector/FallDetectorConfig 단위 테스트.

멀티 프레임 행동 시나리오(정상 보행·낙상·회복·cooldown 등)는
tests/test_fall_pipeline.py에서 다룬다. 이 파일은 설정 로딩과
Event 계약, 상태머신의 기본 동작 단위를 검증한다.
"""

from __future__ import annotations

import json

import pytest

from src.common.types import Track, TrackingResult
from src.safety.fall_detector import FallDetector, FallDetectorConfig

_STANDING_BBOX = [40.0, 0.0, 60.0, 60.0]  # width 20, height 60, aspect_ratio 0.33
_LYING_BBOX = [10.0, 50.0, 90.0, 70.0]  # width 80, height 20, aspect_ratio 4.0


def _fast_config(**overrides) -> FallDetectorConfig:
    """cooldown 등을 짧게 줄인 테스트용 config (동작 원칙은 기본값과 동일)."""
    cfg = FallDetectorConfig(cooldown_sec=1.0)
    for key, value in overrides.items():
        setattr(cfg, key, value)
    return cfg


def _result(
    frame_number, bbox, video_source="cam1", track_id=1, confidence=0.9, timestamp="00:00:00.000"
):
    return TrackingResult(
        frame_number=frame_number,
        timestamp=timestamp,
        video_source=video_source,
        tracks=[Track(track_id=track_id, bbox=list(bbox), foot_point=[
            (bbox[0] + bbox[2]) / 2.0, bbox[3]
        ], confidence=confidence)],
    )


def _feed_standing(detector, num_frames, fps, start_frame=0, video_source="cam1"):
    """track_age_sec 게이트를 통과시키기 위해 정지 상태로 여러 프레임을 먼저 흘린다."""
    events = []
    for i in range(num_frames):
        events += detector.process(
            _result(start_frame + i, _STANDING_BBOX, video_source=video_source)
        )
    return events


class TestFallDetectorConfig:
    def test_defaults_match_configs_fall_detection_json(self):
        """configs/fall_detection.json이 dataclass 기본값과 어긋나지 않는지 확인한다."""
        with open("configs/fall_detection.json", "r", encoding="utf-8") as file:
            data = json.load(file)
        cfg = FallDetectorConfig(**data)
        assert cfg.horizontal_aspect_ratio_threshold == 1.3
        assert cfg.fall_confirm_sec == 0.5
        assert cfg.cooldown_sec == 5.0

    def test_from_file_loads_json(self, tmp_path):
        path = tmp_path / "fall_detection.json"
        path.write_text(json.dumps({"fall_confirm_sec": 0.75, "cooldown_sec": 3.0}))

        cfg = FallDetectorConfig.from_file(str(path))

        assert cfg.fall_confirm_sec == 0.75
        assert cfg.cooldown_sec == 3.0
        # 지정하지 않은 값은 dataclass 기본값을 유지한다.
        assert cfg.horizontal_aspect_ratio_threshold == 1.3


class TestFallDetectorConfigValidation:
    @pytest.mark.parametrize(
        "overrides",
        [
            {"track_grace_sec": -0.1},
            {"min_track_age_sec": -1.0},
            {"fall_candidate_timeout_sec": -1.0},
            {"fall_confirm_sec": -0.5},
            {"cooldown_sec": -1.0},
            {"recovery_velocity_threshold": -0.1},
            {"history_window_sec": 0.0},
            {"fall_center_velocity_threshold": 0.0},
            {"fall_foot_velocity_threshold": 0.0},
            {"horizontal_aspect_ratio_threshold": 0.0},
            {"normal_aspect_ratio_threshold": 0.0},
            {"event_confidence_weights": {"posture": -0.1}},
        ],
    )
    def test_rejects_invalid_values(self, overrides):
        with pytest.raises(ValueError):
            FallDetectorConfig(**overrides)

    def test_rejects_horizontal_threshold_not_greater_than_normal(self):
        with pytest.raises(ValueError):
            FallDetectorConfig(
                horizontal_aspect_ratio_threshold=0.9, normal_aspect_ratio_threshold=0.9
            )

    def test_accepts_default_values(self):
        FallDetectorConfig()  # 기본값은 항상 유효해야 한다 (예외 없이 생성)


class TestFallDetectorInit:
    def test_rejects_non_positive_fps(self):
        with pytest.raises(ValueError):
            FallDetector(fps=0)

    def test_uses_default_config_when_none_given(self):
        detector = FallDetector(fps=10.0)
        assert detector.config.fall_confirm_sec == FallDetectorConfig().fall_confirm_sec


class TestNoEventBelowMinTrackAge:
    def test_sudden_change_before_min_track_age_does_not_enter_candidate(self):
        """min_track_age_sec 미만인 신규 Track은 급격한 변화가 있어도 candidate에 진입하지 않는다."""
        fps = 10.0
        detector = FallDetector(fps=fps, config=_fast_config(min_track_age_sec=1.0))

        # frame 0, 1만 흘려 track_age_sec(0.1초)가 min_track_age_sec(1.0초)에 못 미치게 한다.
        detector.process(_result(0, _STANDING_BBOX))
        events = detector.process(_result(1, _LYING_BBOX))

        assert events == []


class TestSingleFallEmitsOneEvent:
    def test_sustained_lying_posture_confirms_fall_once(self):
        fps = 10.0
        detector = FallDetector(fps=fps, config=_fast_config())

        _feed_standing(detector, num_frames=5, fps=fps)  # track_age >= 0.3초 확보
        events = detector.process(_result(5, _LYING_BBOX))  # 급격한 자세 변화
        assert events == []  # candidate 진입, 아직 confirm 아님

        # fall_confirm_sec(0.5초)만큼 누운 자세 유지 → frame 10(0.5초 경과)에서 confirm
        confirmed = []
        for frame_number in range(6, 11):
            confirmed += detector.process(_result(frame_number, _LYING_BBOX))

        assert len(confirmed) == 1
        event = confirmed[0]
        assert event.event_type == "FALL_SUSPECT"
        assert event.zone_id == "__global__"
        assert event.cause is None
        assert event.track_id == 1
        assert event.video_source == "cam1"
        assert 0.0 <= event.event_confidence <= 1.0

    def test_event_timestamp_matches_tracking_result_timestamp(self):
        """FALL_SUSPECT.timestamp는 TrackingResult.timestamp를 그대로 사용해야 한다.

        Event.create()에 timestamp를 전달하지 않으면 "00:00:00.000" fallback이
        저장되는데, 실제 영상 시각이 아니라서 감지 지연 평가에 쓸 수 없다.
        """
        fps = 10.0
        detector = FallDetector(fps=fps, config=_fast_config())

        _feed_standing(detector, num_frames=5, fps=fps)
        detector.process(_result(5, _LYING_BBOX, timestamp="00:00:12.500"))

        confirmed = []
        for offset, frame_number in enumerate(range(6, 11), start=1):
            ts = f"00:00:{12.5 + offset * 0.1:06.3f}"
            confirmed += detector.process(_result(frame_number, _LYING_BBOX, timestamp=ts))

        assert len(confirmed) == 1
        assert confirmed[0].timestamp == f"00:00:{12.5 + 5 * 0.1:06.3f}"
        assert confirmed[0].timestamp != "00:00:00.000"


class TestEventConfidencePreservesDescentEvidence:
    def test_rapid_fall_has_higher_confidence_than_zero_descent_baseline(self):
        """confirm 시점(정지 상태)의 특징이 아니라 candidate 기간 중 최대 하강 점수를
        event_confidence에 반영해야 한다. 그렇지 않으면 급격한 낙상과 완만한 낙상이
        동일한 점수(posture+duration+track_confidence만 반영된 baseline)로 나온다.
        """
        fps = 10.0
        detector = FallDetector(fps=fps, config=_fast_config())

        _feed_standing(detector, num_frames=5, fps=fps)
        detector.process(_result(5, _LYING_BBOX))  # 급격한 낙상: 큰 하강 속도로 candidate 진입

        confirmed = []
        for frame_number in range(6, 11):
            confirmed += detector.process(_result(frame_number, _LYING_BBOX))

        assert len(confirmed) == 1
        # posture(0.35) + duration(0.2) + track_confidence(0.1*0.9)=0.09 = 0.64가 descent
        # 근거 없이 나오는 baseline. 급격한 낙상은 descent_score가 1.0으로 반영되어
        # 이보다 높은 event_confidence(+0.35)를 가져야 한다.
        assert confirmed[0].event_confidence > 0.64
        assert confirmed[0].event_confidence == pytest.approx(0.99, abs=0.01)


class TestEventConfidenceRange:
    def test_event_confidence_is_always_within_unit_range(self):
        fps = 10.0
        detector = FallDetector(fps=fps, config=_fast_config())
        _feed_standing(detector, num_frames=5, fps=fps)
        detector.process(_result(5, _LYING_BBOX))

        events = []
        for frame_number in range(6, 11):
            events += detector.process(_result(frame_number, _LYING_BBOX))

        assert len(events) == 1
        assert 0.0 <= events[0].event_confidence <= 1.0
