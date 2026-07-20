"""FallDetector/FallDetectorConfig 단위 테스트.

멀티 프레임 행동 시나리오(정상 보행·낙상·회복·cooldown 등)는
tests/test_fall_pipeline.py에서 다룬다. 이 파일은 설정 로딩과
Event 계약, 상태머신의 기본 동작 단위를 검증한다.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from src.common.types import EventCause, EventCauseEvidence, Track, TrackingResult
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
        """configs/fall_detection.json이 dataclass 기본값과 어긋나지 않는지 확인한다.

        FallDetectorConfig.from_file()을 직접 써야 한다 — "cause_attribution"
        섹션(FallCauseAttributorConfig 전용, from_file()이 걸러낸다)을 여기서
        다시 수동으로 흉내내면 실제 로딩 경로와 어긋난다.
        """
        cfg = FallDetectorConfig.from_file("configs/fall_detection.json")
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
            {"fall_confirm_sec": 0.0},
            {"cooldown_sec": -1.0},
            {"recovery_velocity_threshold": -0.1},
            {"history_window_sec": 0.0},
            {"fall_center_velocity_threshold": 0.0},
            {"fall_foot_velocity_threshold": 0.0},
            {"horizontal_aspect_ratio_threshold": 0.0},
            {"normal_aspect_ratio_threshold": 0.0},
            {"event_confidence_weights": {"posture": -0.1}},
            {"model_confirm_sec": 0.0},
            {"model_confirm_sec": -0.5},
            {"model_vote_window_sec": 0.0},
            {"model_vote_window_sec": -0.1},
            {"model_candidate_entry_sec": 0.0},
            {"model_candidate_entry_sec": -0.1},
            {"cooldown_inherit_iou_threshold": 0.0},
            {"cooldown_inherit_iou_threshold": 1.1},
        ],
    )
    def test_rejects_invalid_values(self, overrides):
        with pytest.raises(ValueError):
            FallDetectorConfig(**overrides)

    def test_rejects_window_smaller_than_confirm_sec(self):
        with pytest.raises(ValueError, match="model_vote_window_sec"):
            FallDetectorConfig(model_confirm_sec=0.5, model_vote_window_sec=0.3)

    def test_rejects_entry_sec_not_smaller_than_confirm_sec(self):
        with pytest.raises(ValueError, match="model_candidate_entry_sec"):
            FallDetectorConfig(model_candidate_entry_sec=0.2, model_confirm_sec=0.2)

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


class TestResolveModelEvidence:
    def test_none_dict_disables_model_path(self):
        assert FallDetector._resolve_model_evidence(None, track_id=1) is None

    def test_missing_track_id_becomes_unknown_not_none(self):
        evidence = FallDetector._resolve_model_evidence({}, track_id=1)

        assert evidence is not None
        assert evidence.label == "unknown"
        assert evidence.track_id == 1
        assert evidence.confidence is None
        assert evidence.iou is None

    def test_present_track_id_returned_as_is(self):
        from src.safety.fall_model_matching import FallModelEvidence

        present = FallModelEvidence(track_id=1, label="fall", confidence=0.8, iou=0.5)
        evidence = FallDetector._resolve_model_evidence({1: present}, track_id=1)

        assert evidence is present

    def test_mismatched_key_and_track_id_raises(self):
        """딕셔너리 key(1)와 FallModelEvidence.track_id(2)가 다르면 조용히 쓰면 안 된다."""
        from src.safety.fall_model_matching import FallModelEvidence

        mismatched = FallModelEvidence(track_id=2, label="fall", confidence=0.9, iou=0.9)

        with pytest.raises(ValueError, match="track_id"):
            FallDetector._resolve_model_evidence({1: mismatched}, track_id=1)


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


class TestCauseAttribution:
    """FallDetector가 cause_attributor를 어떻게 호출하는지 검증한다.

    FallCauseAttributor.attribute() 자체의 후보 탐색·점수 계산 로직은
    tests/test_fall_cause_attributor.py에서 이미 순수 시나리오로 검증했다.
    여기서는 "FallDetector가 올바른 인자로, 올바른 시점에 그 메서드를
    호출하는지"만 mock으로 확인한다 — 특히 candidate_since_sec을 리셋 전에
    캡처해 넘기는지가 핵심이다(모듈 docstring, _confirm_fall 참고).
    """

    def test_cause_is_none_when_no_attributor_given(self):
        """cause_attributor를 넘기지 않으면(기본값 None) 기존 PR2 동작과 완전히 동일해야 한다."""
        fps = 10.0
        detector = FallDetector(fps=fps, config=_fast_config())

        _feed_standing(detector, num_frames=5, fps=fps)
        detector.process(_result(5, _LYING_BBOX))
        confirmed = []
        for frame_number in range(6, 11):
            confirmed += detector.process(_result(frame_number, _LYING_BBOX))

        assert len(confirmed) == 1
        assert confirmed[0].cause is None

    def test_attribute_called_with_candidate_entry_time_not_confirm_time(self):
        """가장 중요한 회귀 방지 지점: fall_start_sec은 candidate 진입 시각(frame 5,

        0.5초)이어야 한다 — confirm 시각(frame 10, 1.0초)이 들어가면
        state.candidate_since_sec을 리셋 전에 캡처하지 않았다는 뜻이다.
        """
        fps = 10.0
        detector = FallDetector(fps=fps, config=_fast_config())
        mock_attributor = MagicMock()
        mock_attributor.attribute.return_value = None

        _feed_standing(detector, num_frames=5, fps=fps)
        detector.process(_result(5, _LYING_BBOX), cause_attributor=mock_attributor)
        confirmed = []
        for frame_number in range(6, 11):
            confirmed += detector.process(
                _result(frame_number, _LYING_BBOX), cause_attributor=mock_attributor
            )

        assert len(confirmed) == 1
        mock_attributor.attribute.assert_called_once_with(
            video_source="cam1",
            victim_track_id=1,
            fall_start_sec=pytest.approx(0.5),
        )

    def test_event_cause_is_attributor_return_value(self):
        """attribute()가 EventCause를 반환하면 그대로 Event.cause에 실려야 한다."""
        fps = 10.0
        detector = FallDetector(fps=fps, config=_fast_config())
        expected_cause = EventCause(
            type="NEARBY_TRACK",
            track_id=2,
            score=0.75,
            evidence=EventCauseEvidence(
                min_distance_norm=0.3,
                closing_speed_norm=0.6,
                time_to_fall_sec=0.4,
            ),
        )
        mock_attributor = MagicMock()
        mock_attributor.attribute.return_value = expected_cause

        _feed_standing(detector, num_frames=5, fps=fps)
        detector.process(_result(5, _LYING_BBOX), cause_attributor=mock_attributor)
        confirmed = []
        for frame_number in range(6, 11):
            confirmed += detector.process(
                _result(frame_number, _LYING_BBOX), cause_attributor=mock_attributor
            )

        assert len(confirmed) == 1
        assert confirmed[0].cause is expected_cause

    def test_attribute_not_called_before_confirm(self):
        """candidate 상태에 머무는 동안에는(아직 confirm 아님) attribute()가 호출되면 안 된다."""
        fps = 10.0
        detector = FallDetector(fps=fps, config=_fast_config())
        mock_attributor = MagicMock()
        mock_attributor.attribute.return_value = None

        _feed_standing(detector, num_frames=5, fps=fps)
        events = detector.process(_result(5, _LYING_BBOX), cause_attributor=mock_attributor)

        assert events == []
        mock_attributor.attribute.assert_not_called()

    def test_attribute_exception_does_not_lose_the_fall_suspect_event(self, caplog):
        """cause는 부가 정보다 — attribute()가 예외를 내도 이미 확정된

        FALL_SUSPECT Event 자체는 반드시 반환돼야 한다(fail-closed,
        cause=None). 이 호출 시점에는 이미 COOLDOWN 전이와 tombstone 기록이
        끝난 상태라, 예외를 그대로 전파시키면 Event가 통째로 유실된다.
        """
        fps = 10.0
        detector = FallDetector(fps=fps, config=_fast_config())
        mock_attributor = MagicMock()
        mock_attributor.attribute.side_effect = RuntimeError("attribution 내부 오류")

        _feed_standing(detector, num_frames=5, fps=fps)
        detector.process(_result(5, _LYING_BBOX), cause_attributor=mock_attributor)
        confirmed = []
        for frame_number in range(6, 11):
            confirmed += detector.process(
                _result(frame_number, _LYING_BBOX), cause_attributor=mock_attributor
            )

        assert len(confirmed) == 1
        assert confirmed[0].event_type == "FALL_SUSPECT"
        assert confirmed[0].cause is None
        # Track은 이미 COOLDOWN으로 전이돼 있어야 한다(예외 이전 cleanup은 그대로 진행됨).
        assert detector._states[("cam1", 1)].state == "COOLDOWN"
        # 예외를 조용히 삼키지 않고 로그로는 남겨야 한다.
        assert any(
            record.levelname == "ERROR" and "cause attribution" in record.message
            for record in caplog.records
        )
