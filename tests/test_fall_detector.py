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
from src.safety.fall_model_matching import FallModelEvidence, compute_iou

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


def _feed_standing(detector, num_frames, fps, start_frame=0, video_source="cam1", track_id=1):
    """track_age_sec 게이트를 통과시키기 위해 정지 상태로 여러 프레임을 먼저 흘린다."""
    events = []
    for i in range(num_frames):
        events += detector.process(
            _result(start_frame + i, _STANDING_BBOX, video_source=video_source, track_id=track_id)
        )
    return events


class TestFallDetectorConfig:
    def test_defaults_match_configs_fall_detection_json(self):
        """configs/fall_detection.json이 dataclass 기본값과 어긋나지 않는지 확인한다.

        JSON을 실제로 로드해서(FallDetectorConfig.from_file) dataclass 기본값과
        완전히 같은 인스턴스가 나오는지 비교한다 — 필드가 새로 추가됐는데 JSON에
        반영을 깜빡하면 이 테스트가 실패한다.
        """
        config_from_file = FallDetectorConfig.from_file("configs/fall_detection.json")
        assert config_from_file == FallDetectorConfig()

    def test_from_file_loads_json(self, tmp_path):
        path = tmp_path / "fall_detection.json"
        path.write_text(json.dumps({"fall_confirm_sec": 0.75, "cooldown_sec": 3.0}))

        cfg = FallDetectorConfig.from_file(str(path))

        assert cfg.fall_confirm_sec == 0.75
        assert cfg.cooldown_sec == 3.0
        # 지정하지 않은 값은 dataclass 기본값을 유지한다.
        assert cfg.horizontal_aspect_ratio_threshold == 1.3

    def test_construct_with_defaults(self):
        config = FallDetectorConfig()
        assert config.fall_confirm_sec > 0
        assert config.cooldown_sec > 0

    def test_accepts_default_values(self):
        FallDetectorConfig()  # 예외 없이 생성되어야 한다.


class TestFallDetectorConfigValidation:
    @pytest.mark.parametrize(
        "overrides",
        [
            {"track_grace_sec": -0.1},
            {"min_track_age_sec": -0.1},
            {"min_track_age_sec": -1.0},
            {"fall_candidate_timeout_sec": -0.1},
            {"fall_candidate_timeout_sec": -1.0},
            {"cooldown_sec": -0.1},
            {"cooldown_sec": -1.0},
            {"recovery_velocity_threshold": -0.1},
            {"recovery_confirm_sec": -0.1},
        ],
    )
    def test_rejects_negative_non_strict_fields(self, overrides):
        with pytest.raises(ValueError, match="0 이상"):
            FallDetectorConfig(**overrides)

    @pytest.mark.parametrize(
        "overrides",
        [
            {"fall_confirm_sec": 0.0},
            {"fall_confirm_sec": -0.5},
            {"model_confirm_sec": 0.0},
            {"model_confirm_sec": -0.5},
            {"model_vote_window_sec": 0.0},
            {"model_vote_window_sec": -0.1},
            {"model_candidate_entry_sec": 0.0},
            {"model_candidate_entry_sec": -0.1},
        ],
    )
    def test_rejects_zero_for_strictly_positive_fields(self, overrides):
        with pytest.raises(ValueError, match="0보다 커야"):
            FallDetectorConfig(**overrides)

    @pytest.mark.parametrize(
        "overrides",
        [
            {"history_window_sec": 0.0},
            {"fall_center_velocity_threshold": 0.0},
            {"fall_foot_velocity_threshold": 0.0},
            {"horizontal_aspect_ratio_threshold": 0.0},
            {"normal_aspect_ratio_threshold": 0.0},
        ],
    )
    def test_rejects_zero_for_other_strictly_positive_fields(self, overrides):
        with pytest.raises(ValueError):
            FallDetectorConfig(**overrides)

    def test_model_vote_window_must_be_at_least_model_confirm(self):
        with pytest.raises(ValueError, match="model_vote_window_sec"):
            FallDetectorConfig(model_confirm_sec=0.5, model_vote_window_sec=0.2)

    def test_model_candidate_entry_must_be_less_than_model_confirm(self):
        with pytest.raises(ValueError, match="model_candidate_entry_sec"):
            FallDetectorConfig(model_candidate_entry_sec=0.2, model_confirm_sec=0.2)

    def test_cooldown_inherit_iou_threshold_must_be_in_range(self):
        with pytest.raises(ValueError, match="cooldown_inherit_iou_threshold"):
            FallDetectorConfig(cooldown_inherit_iou_threshold=0.0)
        with pytest.raises(ValueError, match="cooldown_inherit_iou_threshold"):
            FallDetectorConfig(cooldown_inherit_iou_threshold=1.5)

    def test_horizontal_must_exceed_normal_aspect_ratio(self):
        with pytest.raises(ValueError, match="horizontal_aspect_ratio_threshold"):
            FallDetectorConfig(
                horizontal_aspect_ratio_threshold=0.9, normal_aspect_ratio_threshold=0.9
            )

    def test_pose_fallen_threshold_range(self):
        with pytest.raises(ValueError, match="pose_fallen_threshold"):
            FallDetectorConfig(pose_fallen_threshold=1.5)

    def test_negative_event_confidence_weight_rejected(self):
        with pytest.raises(ValueError, match="event_confidence_weights"):
            FallDetectorConfig(event_confidence_weights={"posture": -0.1})


class TestFallDetectorInit:
    def test_rejects_non_positive_fps(self):
        with pytest.raises(ValueError, match="fps"):
            FallDetector(fps=0.0)
        with pytest.raises(ValueError, match="fps"):
            FallDetector(fps=-1.0)

    def test_uses_default_config_when_none_given(self):
        detector = FallDetector(fps=10.0)
        assert detector.config.fall_confirm_sec == FallDetectorConfig().fall_confirm_sec


class TestResolveModelEvidence:
    def test_none_dict_disables_model_path(self):
        assert FallDetector._resolve_model_evidence(None, track_id=1) is None

    def test_missing_track_id_becomes_unknown_not_none(self):
        result = FallDetector._resolve_model_evidence({}, track_id=1)
        assert result.label == "unknown"
        assert result.track_id == 1
        assert result.confidence is None
        assert result.iou is None

    def test_missing_track_id_becomes_unknown(self):
        present = FallModelEvidence(track_id=1, label="fall", confidence=0.8, iou=0.5)
        result = FallDetector._resolve_model_evidence({1: present}, track_id=2)
        assert result.label == "unknown"
        assert result.track_id == 2
        assert result.confidence is None
        assert result.iou is None

    def test_present_track_id_returned_as_is(self):
        present = FallModelEvidence(track_id=1, label="fall", confidence=0.8, iou=0.5)
        result = FallDetector._resolve_model_evidence({1: present}, track_id=1)
        assert result is present

    def test_mismatched_track_id_in_value_raises(self):
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
        assert detector._states[("cam1", 1)].state == "NORMAL"


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
    def test_event_confidence_always_between_zero_and_one(self):
        fps = 10.0
        detector = FallDetector(
            fps=fps,
            config=_fast_config(
                event_confidence_weights={
                    "posture": 10.0,
                    "descent": 10.0,
                    "duration": 10.0,
                    "track_confidence": 10.0,
                }
            ),
        )
        _feed_standing(detector, num_frames=5, fps=fps)
        detector.process(_result(5, _LYING_BBOX))
        confirmed = []
        for frame_number in range(6, 11):
            confirmed += detector.process(_result(frame_number, _LYING_BBOX))
        assert len(confirmed) == 1
        assert 0.0 <= confirmed[0].event_confidence <= 1.0


class TestCauseAttribution:
    """FallDetector가 cause_attributor를 어떻게 호출하는지 검증한다.

    FallCauseAttributor.attribute() 자체의 후보 탐색·점수 계산 로직은
    tests/test_fall_cause_attributor.py에서 이미 순수 시나리오로 검증했다.
    여기서는 "FallDetector가 올바른 인자로, 올바른 시점에 그 메서드를
    호출하는지"만 mock으로 확인한다 — 특히 candidate_since_sec을 리셋 전에
    캡처해 넘기는지가 핵심이다(모듈 docstring, _confirm_fall 참고).
    """

    def test_cause_is_none_when_no_attributor_given(self):
        """cause_attributor를 넘기지 않으면 기존 낙상 감지 동작을 유지한다."""
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
            victim_track_id_aliases=frozenset(),
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


class TestDiagnostics:
    """평가 프로토콜 V2의 candidate 진입 이유와 confirm 경로 진단.

    Event dataclass 자체는 건드리지 않는 side-channel이라, diagnostics=None(기본값)이면
    기존 동작과 완전히 동일해야 하고, 넘기면 confirm마다 dict 하나가 append돼야 한다.
    """

    def test_diagnostics_none_by_default_does_not_change_behavior(self):
        fps = 10.0
        detector = FallDetector(fps=fps, config=_fast_config())

        _feed_standing(detector, num_frames=5, fps=fps)
        detector.process(_result(5, _LYING_BBOX))
        confirmed = []
        for frame_number in range(6, 11):
            confirmed += detector.process(_result(frame_number, _LYING_BBOX))

        assert len(confirmed) == 1  # diagnostics 인자를 아예 안 넘겨도 기존처럼 confirm된다.

    def test_bbox_confirm_records_dynamic_entry_and_bbox_path(self):
        fps = 10.0
        detector = FallDetector(fps=fps, config=_fast_config())
        diagnostics: list = []

        _feed_standing(detector, num_frames=5, fps=fps)
        detector.process(_result(5, _LYING_BBOX), diagnostics=diagnostics)
        confirmed = []
        for frame_number in range(6, 11):
            confirmed += detector.process(
                _result(frame_number, _LYING_BBOX), diagnostics=diagnostics
            )

        assert len(confirmed) == 1
        assert diagnostics == [
            {
                "video_source": "cam1",
                "track_id": 1,
                "frame_number": 10,
                "confirm_path": "bbox",
                "candidate_entry_reason": "dynamic",
            }
        ]

    def test_model_only_confirm_records_model_entry_and_model_path(self):
        """서 있는 자세(dynamic 근거 없음)에서 보조 모델의 fall 라벨만으로

        candidate에 진입하고 confirm되는 경로 — candidate_entry_reason과
        confirm_path 둘 다 "model"이어야 한다.
        """
        fps = 10.0
        detector = FallDetector(fps=fps, config=_fast_config())
        diagnostics: list = []
        fall_evidence = {1: FallModelEvidence(track_id=1, label="fall", confidence=0.9, iou=0.8)}

        _feed_standing(detector, num_frames=5, fps=fps)  # track_age 확보, dynamic 근거 없음
        events = []
        for frame_number in range(5, 8):
            events += detector.process(
                _result(frame_number, _STANDING_BBOX),
                model_evidence=fall_evidence,
                diagnostics=diagnostics,
            )

        assert len(events) == 1
        assert len(diagnostics) == 1
        assert diagnostics[0]["confirm_path"] == "model"
        assert diagnostics[0]["candidate_entry_reason"] == "model"

    def test_diagnostics_not_appended_while_still_candidate(self):
        fps = 10.0
        detector = FallDetector(fps=fps, config=_fast_config())
        diagnostics: list = []

        _feed_standing(detector, num_frames=5, fps=fps)
        events = detector.process(_result(5, _LYING_BBOX), diagnostics=diagnostics)

        assert events == []
        assert diagnostics == []


def _multi_result(frame_number, tracks, video_source="cam1", timestamp="00:00:00.000"):
    """tracks: (track_id, bbox) 튜플 목록 — 한 프레임에 여러 Track이 있는 시나리오용."""
    return TrackingResult(
        frame_number=frame_number,
        timestamp=timestamp,
        video_source=video_source,
        tracks=[
            Track(
                track_id=track_id,
                bbox=list(bbox),
                foot_point=[(bbox[0] + bbox[2]) / 2.0, bbox[3]],
                confidence=0.9,
            )
            for track_id, bbox in tracks
        ],
    )


class TestCandidateHandoff:
    """ReID 없이 candidate 도중 Track을 놓친 뒤 새 Track ID로 재검출됐을 때

    candidate 진행 상황을 물려받는지 검증한다.

    새 Track의 상태는 FallFeatureExtractor가 속도를 계산할 최소 2개의 history
    샘플이 쌓여야(process()의 `if features is None: continue` 게이트) 비로소
    만들어진다 — 즉 handoff는 새 Track이 처음 나타난 프레임이 아니라 "두 번째로"
    나타난 프레임에 일어난다. tombstone 자체는(process() 최상단, 메인 루프
    이전) Track이 사라진 바로 그 프레임에 이미 등록된다. 아래 테스트들은 이
    순서를 그대로 반영한다.
    """

    def test_new_track_at_same_location_inherits_candidate_since_sec(self):
        fps = 10.0
        detector = FallDetector(fps=fps, config=_fast_config())

        _feed_standing(detector, num_frames=5, fps=fps)  # track 1, frame 0~4
        detector.process(_result(5, _LYING_BBOX, track_id=1))  # frame 5: candidate 진입, t=0.5

        # frame 6: track 1은 사라지고(→ 이 프레임에 tombstone 등록), 같은
        # 위치에 track 2가 처음 나타난다(아직 history 1개, state 생성 안 됨).
        detector.process(_multi_result(6, [(2, _LYING_BBOX)]))
        assert ("cam1", 2) not in detector._states

        # frame 7: track 2가 두 번째로 나타나 features가 계산되고, 이 시점에
        # handoff가 일어난다.
        detector.process(_multi_result(7, [(2, _LYING_BBOX)]))

        new_state = detector._states[("cam1", 2)]
        assert new_state.state == "FALLING_CANDIDATE"
        assert new_state.candidate_since_sec == pytest.approx(0.5)  # track 1의 원래 진입 시각
        assert new_state.candidate_entry_reason == "handoff"
        assert new_state.origin_track_ids == frozenset({1})

    def test_duration_fields_are_not_carried_over(self):
        """horizontal/pose/model duration은 승계하지 않는다 — 새 Track에서 정적

        근거를 다시 쌓아야 근거 없이 즉시 confirm되지 않는다(모듈 docstring).
        """
        fps = 10.0
        detector = FallDetector(fps=fps, config=_fast_config())

        _feed_standing(detector, num_frames=5, fps=fps)
        detector.process(_result(5, _LYING_BBOX, track_id=1))
        # frame 6~7: track 1이 계속 누워 있어 horizontal_duration_sec이 쌓인다
        # (fall_confirm_sec=0.5초=5프레임에는 아직 못 미침).
        detector.process(_result(6, _LYING_BBOX, track_id=1))
        detector.process(_result(7, _LYING_BBOX, track_id=1))
        assert detector._states[("cam1", 1)].horizontal_duration_sec > 0.0

        detector.process(_multi_result(8, [(2, _LYING_BBOX)]))
        detector.process(_multi_result(9, [(2, _LYING_BBOX)]))

        new_state = detector._states[("cam1", 2)]
        assert new_state.state == "FALLING_CANDIDATE"  # 승계는 됐지만
        assert new_state.horizontal_duration_sec == 0.0  # duration은 새로 쌓아야 함
        assert new_state.pose_duration_sec == 0.0
        assert new_state.model_duration_sec == 0.0

    def test_handoff_track_confirms_using_original_candidate_since_sec(self):
        """승계받은 Track이 confirm되면, cause attribution의 fall_start_sec은

        새 Track이 나타난 시각이 아니라 원래 candidate 진입 시각이어야 한다
        (기존 회귀 테스트와 같은 패턴 — 이번엔 handoff를 거친 경우).
        """
        fps = 10.0
        detector = FallDetector(fps=fps, config=_fast_config())
        mock_attributor = MagicMock()
        mock_attributor.attribute.return_value = None

        _feed_standing(detector, num_frames=5, fps=fps)
        detector.process(_result(5, _LYING_BBOX, track_id=1))  # candidate 진입, t=0.5

        detector.process(_multi_result(6, [(2, _LYING_BBOX)]), cause_attributor=mock_attributor)
        detector.process(  # frame 7: handoff 발생
            _multi_result(7, [(2, _LYING_BBOX)]), cause_attributor=mock_attributor
        )
        # frame 8~12(5프레임): fall_confirm_sec(0.5초)만큼 누운 자세 유지 -> confirm.
        confirmed = []
        for frame_number in range(8, 13):
            confirmed += detector.process(
                _result(frame_number, _LYING_BBOX, track_id=2), cause_attributor=mock_attributor
            )

        assert len(confirmed) == 1
        assert confirmed[0].track_id == 2  # Event.track_id는 항상 현재(재획득) Track ID
        mock_attributor.attribute.assert_called_once_with(
            video_source="cam1",
            victim_track_id=2,
            fall_start_sec=pytest.approx(0.5),  # track 1이 진입한 시각
            victim_track_id_aliases=frozenset({1}),  # handoff 이전 alias
        )

    def test_no_handoff_across_different_video_source(self):
        fps = 10.0
        detector = FallDetector(fps=fps, config=_fast_config())

        _feed_standing(detector, num_frames=5, fps=fps, video_source="cam1")
        detector.process(_result(5, _LYING_BBOX, track_id=1, video_source="cam1"))

        detector.process(_multi_result(6, [(2, _LYING_BBOX)], video_source="cam2"))
        detector.process(_multi_result(7, [(2, _LYING_BBOX)], video_source="cam2"))

        assert detector._states[("cam2", 2)].state == "NORMAL"

    def test_no_handoff_after_ttl_expires(self):
        fps = 10.0
        detector = FallDetector(fps=fps, config=_fast_config(candidate_handoff_ttl_sec=0.2))

        _feed_standing(detector, num_frames=5, fps=fps)
        detector.process(_result(5, _LYING_BBOX, track_id=1))  # t=0.5, tombstone 만료=0.7

        # track 2가 TTL이 지난 뒤에야(t=0.9, 0.7 초과) 나타난다.
        detector.process(_multi_result(9, [(2, _LYING_BBOX)]))
        detector.process(_multi_result(10, [(2, _LYING_BBOX)]))

        assert detector._states[("cam1", 2)].state == "NORMAL"

    def test_no_handoff_after_candidate_timeout_even_within_ttl(self):
        """TTL은 안 지났어도, candidate 자체의 fall_candidate_timeout_sec을

        넘겼으면 승계하지 않는다 — 이미 타임아웃됐어야 할 candidate가 다른
        Track에서 부활하면 안 된다.
        """
        fps = 10.0
        detector = FallDetector(
            fps=fps,
            config=_fast_config(candidate_handoff_ttl_sec=10.0, fall_candidate_timeout_sec=0.3),
        )

        _feed_standing(detector, num_frames=5, fps=fps)
        detector.process(_result(5, _LYING_BBOX, track_id=1))  # t=0.5, candidate 만료=0.8

        detector.process(_multi_result(9, [(2, _LYING_BBOX)]))  # t=0.9 > 0.8
        detector.process(_multi_result(10, [(2, _LYING_BBOX)]))

        assert detector._states[("cam1", 2)].state == "NORMAL"

    def test_no_handoff_when_bbox_far_apart(self):
        fps = 10.0
        detector = FallDetector(fps=fps, config=_fast_config())

        _feed_standing(detector, num_frames=5, fps=fps)
        detector.process(_result(5, _LYING_BBOX, track_id=1))

        far_bbox = [500.0, 500.0, 580.0, 520.0]  # 전혀 겹치지 않는 위치
        detector.process(_multi_result(6, [(2, far_bbox)]))
        detector.process(_multi_result(7, [(2, far_bbox)]))

        assert detector._states[("cam1", 2)].state == "NORMAL"

    def test_cooldown_inherit_takes_priority_over_candidate_handoff(self):
        """같은 자리에 cooldown tombstone과 candidate tombstone이 모두 있으면

        cooldown 승계가 항상 우선한다.
        """
        fps = 10.0
        detector = FallDetector(fps=fps, config=_fast_config())

        # track 1을 실제로 confirm시켜 cooldown tombstone을 만든다.
        _feed_standing(detector, num_frames=5, fps=fps, video_source="cam1")
        detector.process(_result(5, _LYING_BBOX, track_id=1))
        confirmed = []
        for frame_number in range(6, 11):
            confirmed += detector.process(_result(frame_number, _LYING_BBOX, track_id=1))
        assert len(confirmed) == 1

        # track 3을 같은 자리에서 candidate로 만든 뒤(track 1과는 별개 ID) 그대로 둔다.
        _feed_standing(
            detector, num_frames=5, fps=fps, start_frame=11, video_source="cam1", track_id=3
        )
        detector.process(_result(16, _LYING_BBOX, track_id=3))
        assert detector._states[("cam1", 3)].state == "FALLING_CANDIDATE"

        # track 4가 두 프레임 연속 나타나면, 같은 위치에 cooldown(track1)과
        # candidate(track3) tombstone이 모두 있다(track3이 사라진 이 프레임에
        # candidate tombstone이 등록된다) — cooldown이 우선해야 한다.
        detector.process(_multi_result(17, [(4, _LYING_BBOX)]))
        detector.process(_multi_result(18, [(4, _LYING_BBOX)]))

        assert detector._states[("cam1", 4)].state == "COOLDOWN"

    def test_original_track_reappearing_cancels_tombstone(self):
        """원본 Track이 tombstone 만료 전에 재등장하면, 그 자신은 그대로

        이어가고(자기 상태가 살아있으므로) tombstone은 취소돼 다른 Track이
        나중에 가로챌 수 없다.
        """
        fps = 10.0
        detector = FallDetector(fps=fps, config=_fast_config())

        _feed_standing(detector, num_frames=5, fps=fps)
        detector.process(_result(5, _LYING_BBOX, track_id=1))  # candidate 진입

        # frame 6: track 1 소실(사라짐) — 이 시점에 tombstone 등록.
        detector.process(_multi_result(6, []))
        assert "cam1" in detector._candidate_tombstones

        # frame 7: track 1이 다시 나타난다 — tombstone은 취소돼야 한다.
        detector.process(_result(7, _LYING_BBOX, track_id=1))
        assert detector._candidate_tombstones.get("cam1", []) == []
        assert detector._states[("cam1", 1)].state == "FALLING_CANDIDATE"  # 자기 상태 그대로 유지

        # frame 8~9: track 2가 나타나도(2프레임 연속) 이미 취소된 tombstone을
        # 승계할 수 없다.
        detector.process(_multi_result(8, [(1, _LYING_BBOX), (2, _LYING_BBOX)]))
        detector.process(_multi_result(9, [(1, _LYING_BBOX), (2, _LYING_BBOX)]))
        assert detector._states[("cam1", 2)].state == "NORMAL"

    def test_same_track_id_reappears_after_own_state_purged_by_grace_period(self):
        """track_grace_sec이 candidate_handoff_ttl_sec보다 짧으면, 소실 중

        track_grace_sec을 넘겨 원본 _TrackState 자체가 `_forget_lost_tracks()`
        로 지워질 수 있다(FALLING_CANDIDATE는 COOLDOWN과 달리 무조건
        정리 대상). 이 상태에서 tombstone TTL 이내에 같은 track_id가
        재등장하면, "자기 상태가 살아있으니 취소"로 잘못 처리해 진행
        상황을 통째로 잃으면 안 되고 handoff로 재구성해야 한다.
        """
        fps = 10.0
        detector = FallDetector(
            fps=fps,
            config=_fast_config(
                track_grace_sec=0.2, candidate_handoff_ttl_sec=1.0,
                fall_candidate_timeout_sec=2.0,
            ),
        )

        _feed_standing(detector, num_frames=5, fps=fps)
        detector.process(_result(5, _LYING_BBOX, track_id=1))  # candidate 진입, t=0.5
        assert detector._states[("cam1", 1)].state == "FALLING_CANDIDATE"

        # track_grace_sec(0.2초)은 넘지만 candidate_handoff_ttl_sec(1.0초)
        # 이내로 0.6초 소실된다.
        for frame_number in range(6, 12):
            detector.process(_multi_result(frame_number, []))
        assert ("cam1", 1) not in detector._states  # 원본 상태는 이미 정리됨

        # frame 12~13: 같은 track_id로 재등장(2프레임 규칙).
        detector.process(_result(12, _LYING_BBOX, track_id=1))
        detector.process(_result(13, _LYING_BBOX, track_id=1))

        new_state = detector._states[("cam1", 1)]
        assert new_state.state == "FALLING_CANDIDATE"
        assert new_state.candidate_since_sec == pytest.approx(0.5)  # 원래 진입 시각 유지

    def test_consumed_tombstone_is_not_recreated_next_frame(self):
        """승계로 소비된 tombstone이 다음 프레임에 되살아나면 안 된다.

        원본 Track의 _TrackState가 FALLING_CANDIDATE로 남아있으면
        _update_candidate_tombstones()가 이를 다시 발견해 방금 소비한
        tombstone을 재생성한다 — 그러면 다른 Track이 같은 candidate를
        중복 승계하거나, 원본과 새 Track이 각각 confirm돼 중복 Event가
        생길 수 있다.
        """
        fps = 10.0
        detector = FallDetector(fps=fps, config=_fast_config())

        _feed_standing(detector, num_frames=5, fps=fps)
        detector.process(_result(5, _LYING_BBOX, track_id=1))  # candidate 진입

        detector.process(_multi_result(6, [(2, _LYING_BBOX)]))
        detector.process(_multi_result(7, [(2, _LYING_BBOX)]))  # frame 7: handoff 발생
        assert detector._states[("cam1", 2)].state == "FALLING_CANDIDATE"
        assert ("cam1", 1) not in detector._states  # 원본 상태는 지워져야 한다

        # frame 8: track 2만 계속 나타난다 — 이 시점에 tombstone이 재생성되면
        # 안 된다.
        detector.process(_multi_result(8, [(2, _LYING_BBOX)]))
        assert detector._candidate_tombstones.get("cam1", []) == []

    def test_alias_returns_to_original_track_id_after_second_handoff(self):
        """1 -> 2 -> 1처럼 alias가 원래 id로 돌아와도 candidate 진행 상태가

        사라지면 안 된다. 전체 alias를 조건 없이 지우면
        지금 막 승계받은 바로 그 Track 1의 상태까지 삭제돼 진행 상황이
        통째로 사라진다.
        """
        fps = 10.0
        detector = FallDetector(fps=fps, config=_fast_config())

        _feed_standing(detector, num_frames=5, fps=fps)
        detector.process(_result(5, _LYING_BBOX, track_id=1))  # candidate 진입, t=0.5

        detector.process(_multi_result(6, [(2, _LYING_BBOX)]))
        detector.process(_multi_result(7, [(2, _LYING_BBOX)]))  # track 1 -> 2 승계
        assert detector._states[("cam1", 2)].state == "FALLING_CANDIDATE"

        # frame 8: track 2도 사라진다 -> tombstone(source=2, alias={1, 2}) 등록.
        detector.process(_multi_result(8, []))

        # frame 9: track 1이 grace period 안에서 다시 나타난다 -> 2 -> 1 승계.
        detector.process(_result(9, _LYING_BBOX, track_id=1))

        new_state = detector._states[("cam1", 1)]
        assert new_state.state == "FALLING_CANDIDATE"
        assert new_state.candidate_since_sec == pytest.approx(0.5)  # 최초 진입 시각 유지
        assert new_state.origin_track_ids == frozenset({2})

    def test_multi_hop_handoff_keeps_full_alias_chain(self):
        """Track 1 -> 2 -> 3으로 두 번 승계되면 origin_track_ids가 {1, 2}로

        누적되어야 한다(cause attribution의 victim_track_ids 별칭 체인용).
        """
        fps = 10.0
        detector = FallDetector(fps=fps, config=_fast_config())

        _feed_standing(detector, num_frames=5, fps=fps)
        detector.process(_result(5, _LYING_BBOX, track_id=1))  # candidate 진입, track 1

        detector.process(_multi_result(6, [(2, _LYING_BBOX)]))
        detector.process(_multi_result(7, [(2, _LYING_BBOX)]))  # track 1 -> 2 승계
        assert detector._states[("cam1", 2)].state == "FALLING_CANDIDATE"
        assert detector._states[("cam1", 2)].origin_track_ids == frozenset({1})

        detector.process(_multi_result(8, [(3, _LYING_BBOX)]))
        detector.process(_multi_result(9, [(3, _LYING_BBOX)]))  # track 2 -> 3 승계

        new_state = detector._states[("cam1", 3)]
        assert new_state.state == "FALLING_CANDIDATE"
        assert new_state.origin_track_ids == frozenset({1, 2})
        assert new_state.candidate_since_sec == pytest.approx(0.5)  # 최초 진입 시각 유지
        assert ("cam1", 1) not in detector._states
        assert ("cam1", 2) not in detector._states

    def test_no_handoff_when_foot_distance_exceeds_threshold_despite_iou_pass(self):
        """IoU는 기준을 넘지만 발 위치 거리가 기준을 넘으면 승계하지 않는다."""
        fps = 10.0
        detector = FallDetector(
            fps=fps,
            config=_fast_config(
                candidate_handoff_iou_threshold=0.1,
                candidate_handoff_max_foot_distance_norm=0.05,
            ),
        )

        _feed_standing(detector, num_frames=5, fps=fps)
        detector.process(_result(5, _LYING_BBOX, track_id=1))  # candidate 진입

        # _LYING_BBOX와 IoU는 충분히 겹치지만(가로로 넓게 겹침) 발 위치는
        # 옆으로 크게 떨어진 bbox.
        shifted_bbox = [55.0, 50.0, 135.0, 70.0]
        assert compute_iou(_LYING_BBOX, shifted_bbox) >= 0.1

        detector.process(_multi_result(6, [(2, shifted_bbox)]))
        detector.process(_multi_result(7, [(2, shifted_bbox)]))

        assert detector._states[("cam1", 2)].state == "NORMAL"

    def test_tombstone_consumed_by_only_one_track(self):
        """tombstone 하나당 새 Track 하나만 승계한다 — 같은 자리에 동시에

        나타난 두 번째 Track은 승계받지 못한다.
        """
        fps = 10.0
        detector = FallDetector(fps=fps, config=_fast_config())

        _feed_standing(detector, num_frames=5, fps=fps)
        detector.process(_result(5, _LYING_BBOX, track_id=1))

        detector.process(_multi_result(6, [(2, _LYING_BBOX), (3, _LYING_BBOX)]))
        detector.process(_multi_result(7, [(2, _LYING_BBOX), (3, _LYING_BBOX)]))

        states = [
            detector._states[("cam1", 2)].state,
            detector._states[("cam1", 3)].state,
        ]
        assert states.count("FALLING_CANDIDATE") == 1  # 둘 중 하나만 승계
        assert states.count("NORMAL") == 1


class TestCandidateHandoffConfigValidation:
    def test_rejects_non_positive_ttl(self):
        with pytest.raises(ValueError, match="candidate_handoff_ttl_sec"):
            FallDetectorConfig(candidate_handoff_ttl_sec=0.0)

    def test_rejects_invalid_iou_threshold(self):
        with pytest.raises(ValueError, match="candidate_handoff_iou_threshold"):
            FallDetectorConfig(candidate_handoff_iou_threshold=0.0)
        with pytest.raises(ValueError, match="candidate_handoff_iou_threshold"):
            FallDetectorConfig(candidate_handoff_iou_threshold=1.5)

    def test_rejects_non_positive_foot_distance(self):
        with pytest.raises(ValueError, match="candidate_handoff_max_foot_distance_norm"):
            FallDetectorConfig(candidate_handoff_max_foot_distance_norm=0.0)


class TestCooldownHandoff:
    """Cooldown Handoff (Development/Validation 실측, S7_fall_right·

    S8_fall_backwards 중복 Event 회귀 테스트). 기존 cooldown_inherit
    (confirm 시점 bbox, IoU만, cooldown_until_sec 기준 만료)이 실패했을
    때만 이 경로가 시도된다 — FallDetectorConfig.cooldown_handoff_ttl_sec
    주석 참고.
    """

    # 위쪽이 가려져(occlusion) 높이만 줄어든 재검출을 흉내낸다 — foot_point
    # (바닥 중심)는 그대로 유지한 채 bbox 높이만 12.5로 줄면 IoU=0.25
    # (cooldown_handoff_iou_threshold 0.2는 넘지만 기존
    # cooldown_inherit_iou_threshold 0.3에는 못 미침), foot_dist_norm=0.0
    # (cooldown_handoff_max_foot_distance_norm 0.5 이내).
    _CONFIRM_BBOX = [0.0, 0.0, 90.0, 50.0]  # aspect 1.8
    _SHIFTED_BBOX = [0.0, 37.5, 90.0, 50.0]  # aspect 7.2, 같은 foot_point

    def test_same_track_id_reappears_after_cooldown_numerically_expired_while_missing(self):
        """S7_fall_right 재현: 소실 중 cooldown_until_sec이 지나 _TrackState와

        기존 tombstone이 모두 사라져도, cooldown_handoff_ttl_sec 이내
        재등장이면 COOLDOWN을 승계해 재확정을 막아야 한다.
        """
        fps = 10.0
        detector = FallDetector(
            fps=fps, config=_fast_config(cooldown_sec=0.3, track_grace_sec=0.2)
        )

        _feed_standing(detector, num_frames=5, fps=fps)
        detector.process(_result(5, _LYING_BBOX, track_id=1))
        confirmed = []
        for frame_number in range(6, 11):
            confirmed += detector.process(_result(frame_number, _LYING_BBOX, track_id=1))
        assert len(confirmed) == 1
        assert detector._states[("cam1", 1)].state == "COOLDOWN"

        # track 1이 1.0초(cooldown_sec 0.3초·track_grace_sec 0.2초 모두 초과,
        # cooldown_handoff_ttl_sec 2.0초 이내) 동안 완전히 소실된다.
        for frame_number in range(11, 21):
            detector.process(_multi_result(frame_number, []))
        assert ("cam1", 1) not in detector._states  # 기존 _states는 이미 지워짐
        assert detector._cooldown_tombstones.get("cam1", []) == []  # 기존 tombstone도 만료

        # frame 21: 같은 track_id로 재등장(1번째 관측, 아직 handoff 안 됨).
        detector.process(_result(21, _LYING_BBOX, track_id=1))
        # frame 22: 2번째 관측에서 handoff가 일어난다(2프레임 규칙, 모듈 docstring).
        detector.process(_result(22, _LYING_BBOX, track_id=1))
        assert detector._states[("cam1", 1)].state == "COOLDOWN"

        for frame_number in range(23, 28):
            confirmed += detector.process(_result(frame_number, _LYING_BBOX, track_id=1))
        assert len(confirmed) == 1  # 재확정 없음

    def test_different_track_id_inherits_when_inherit_iou_fails_but_handoff_iou_passes(self):
        """S8_fall_backwards 재현: 기존 cooldown_inherit_iou_threshold(0.3)에는

        못 미치지만 cooldown_handoff_iou_threshold(0.2)와 foot 거리는 통과하는
        경우 COOLDOWN을 승계해야 한다.
        """
        fps = 10.0
        detector = FallDetector(fps=fps, config=_fast_config())

        _feed_standing(detector, num_frames=5, fps=fps)
        detector.process(_result(5, self._CONFIRM_BBOX, track_id=1))
        confirmed = []
        for frame_number in range(6, 11):
            confirmed += detector.process(_result(frame_number, self._CONFIRM_BBOX, track_id=1))
        assert len(confirmed) == 1

        # track 1 소실, 다른 track_id(2)가 살짝 이동한 위치에서 재검출된다.
        detector.process(_multi_result(11, [(2, self._SHIFTED_BBOX)]))
        detector.process(_multi_result(12, [(2, self._SHIFTED_BBOX)]))

        assert detector._states[("cam1", 2)].state == "COOLDOWN"
        for frame_number in range(13, 18):
            confirmed += detector.process(_result(frame_number, self._SHIFTED_BBOX, track_id=2))
        assert len(confirmed) == 1  # 재확정 없음

    def test_no_handoff_when_iou_below_handoff_threshold(self):
        """cooldown_handoff_iou_threshold(0.2)에도 못 미치면 승계하지 않는다."""
        fps = 10.0
        detector = FallDetector(fps=fps, config=_fast_config())

        far_bbox = [500.0, 500.0, 560.0, 560.0]  # 전혀 겹치지 않는 위치

        _feed_standing(detector, num_frames=5, fps=fps)
        detector.process(_result(5, self._CONFIRM_BBOX, track_id=1))
        for frame_number in range(6, 11):
            detector.process(_result(frame_number, self._CONFIRM_BBOX, track_id=1))

        detector.process(_multi_result(11, [(2, far_bbox)]))
        detector.process(_multi_result(12, [(2, far_bbox)]))

        assert detector._states[("cam1", 2)].state == "NORMAL"

    def test_tombstone_expiry_uses_cooldown_until_sec_as_floor(self):
        """tombstone 만료는 last_seen+TTL과 cooldown_until_sec 중 늦은 쪽까지다.

        cooldown_sec을 길게,
        cooldown_handoff_ttl_sec을 짧게 잡아 TTL만으로는 이미 만료됐을
        시점에도 cooldown_until_sec이 남아있으면 여전히 승계돼야 함을
        확인한다. self._CONFIRM_BBOX/_SHIFTED_BBOX(IoU 0.25)를 써서 기존
        cooldown_inherit_iou_threshold(0.3)로는 매칭되지 않게 만든다 —
        그러지 않으면 기존 cooldown_inherit(confirm 시점 tombstone, 이것도
        cooldown_until_sec까지 유효하다)이 먼저 성공해 이 테스트가 실제로는
        max() 하한 로직을 전혀 검증하지 못한 채 통과할 수 있다.
        """
        fps = 10.0
        detector = FallDetector(
            fps=fps, config=_fast_config(cooldown_sec=3.0, cooldown_handoff_ttl_sec=0.5)
        )

        _feed_standing(detector, num_frames=5, fps=fps)
        detector.process(_result(5, self._CONFIRM_BBOX, track_id=1))
        for frame_number in range(6, 11):
            detector.process(_result(frame_number, self._CONFIRM_BBOX, track_id=1))
        assert detector._states[("cam1", 1)].cooldown_until_sec == pytest.approx(4.0)

        # track 1 소실. t=2.1s 시점(마지막 관측 t=1.0s로부터 1.1초 경과,
        # cooldown_handoff_ttl_sec 0.5초는 이미 넘겼지만 cooldown_until_sec
        # (4.0s)은 아직 한참 남음)에 새 track_id로 재등장.
        detector.process(_multi_result(20, [(2, self._SHIFTED_BBOX)]))
        detector.process(_multi_result(21, [(2, self._SHIFTED_BBOX)]))

        assert detector._states[("cam1", 2)].state == "COOLDOWN"

    def test_tombstone_still_expires_after_both_cooldown_and_ttl_pass(self):
        """cooldown_until_sec과 TTL 유예 모두 지나면(카메라 밖으로 나간 경우

        등) 여전히 만료돼야 한다 — cooldown_until_sec을 무조건 하한으로
        쓰되, 무기한 보존은 아니어야 한다.
        """
        fps = 10.0
        detector = FallDetector(
            fps=fps, config=_fast_config(cooldown_sec=0.3, cooldown_handoff_ttl_sec=0.5)
        )

        _feed_standing(detector, num_frames=5, fps=fps)
        detector.process(_result(5, _LYING_BBOX, track_id=1))
        for frame_number in range(6, 11):
            detector.process(_result(frame_number, _LYING_BBOX, track_id=1))
        cooldown_until = detector._states[("cam1", 1)].cooldown_until_sec
        assert cooldown_until == pytest.approx(1.3)

        # track 1이 아주 오래(5초) 소실된다 — cooldown_until_sec(1.3s)과
        # TTL 유예(last_seen 1.0s + 0.5s = 1.5s) 모두 넘긴다.
        for frame_number in range(11, 61):
            detector.process(_multi_result(frame_number, []))

        detector.process(_result(61, _LYING_BBOX, track_id=1))
        detector.process(_result(62, _LYING_BBOX, track_id=1))
        assert detector._states[("cam1", 1)].state == "NORMAL"

    def test_consumed_tombstone_is_not_recreated_next_frame(self):
        """승계로 소비된 tombstone이 다음 프레임에 되살아나면 안 된다

        (Candidate Handoff와 동일한 회귀 — 원본 상태를 지우지 않으면
        재생성돼 다른 Track이 중복 승계할 수 있다). cooldown_sec을 짧게
        잡아 기존 cooldown_inherit이 아니라 이 Cooldown Handoff 경로가
        실제로 실행되도록 한다(test_origin_track_ids_cleared_after_
        genuine_recovery와 같은 이유).
        """
        fps = 10.0
        detector = FallDetector(fps=fps, config=_fast_config(cooldown_sec=0.1))

        _feed_standing(detector, num_frames=5, fps=fps)
        detector.process(_result(5, _LYING_BBOX, track_id=1))
        for frame_number in range(6, 11):
            detector.process(_result(frame_number, _LYING_BBOX, track_id=1))

        detector.process(_multi_result(11, [(2, _LYING_BBOX)]))
        detector.process(_multi_result(12, [(2, _LYING_BBOX)]))  # handoff 발생 (1 -> 2)
        assert detector._states[("cam1", 2)].state == "COOLDOWN"
        assert ("cam1", 1) not in detector._states  # 원본 상태는 지워져야 한다

        # frame 13: track 2만 계속 나타난다 — 이 시점에 tombstone이
        # 재생성되면 안 된다.
        detector.process(_multi_result(13, [(2, _LYING_BBOX)]))
        assert detector._cooldown_handoff_tombstones.get("cam1", []) == []

    def test_origin_track_ids_cleared_after_genuine_recovery(self):
        """Cooldown Handoff로 승계받은 뒤 실제로 회복(NORMAL)하면

        origin_track_ids가 비워져야 한다 — 그러지 않으면 다음 낙상의
        cause attribution에 이전 낙상의 alias가 잘못 섞여 들어간다.

        cooldown_sec을 아주 짧게 잡아, track 2의 두 번째 관측 시점에는
        기존 cooldown_inherit(confirm 시점 tombstone)이 이미 만료돼
        Cooldown Handoff 경로가 실제로 실행되도록 한다 — 그렇지 않으면
        기존 경로가 먼저 매칭돼(cooldown_inherit_iou_threshold 통과) 이
        테스트가 origin_track_ids 채우는 로직을 전혀 실행하지 않는다.
        """
        fps = 10.0
        detector = FallDetector(fps=fps, config=_fast_config(cooldown_sec=0.1))

        _feed_standing(detector, num_frames=5, fps=fps)
        detector.process(_result(5, _LYING_BBOX, track_id=1))
        for frame_number in range(6, 11):
            detector.process(_result(frame_number, _LYING_BBOX, track_id=1))

        detector.process(_multi_result(11, [(2, _LYING_BBOX)]))
        detector.process(_multi_result(12, [(2, _LYING_BBOX)]))  # track1->2 handoff
        assert detector._states[("cam1", 2)].origin_track_ids == frozenset({1})

        # track 2가 이제 일어서서(standing) 회복 조건을 채운다.
        for frame_number in range(13, 20):
            detector.process(_result(frame_number, _STANDING_BBOX, track_id=2))

        assert detector._states[("cam1", 2)].state == "NORMAL"
        assert detector._states[("cam1", 2)].origin_track_ids == frozenset()


class TestCooldownHandoffConfigValidation:
    def test_rejects_non_positive_ttl(self):
        with pytest.raises(ValueError, match="cooldown_handoff_ttl_sec"):
            FallDetectorConfig(cooldown_handoff_ttl_sec=0.0)

    def test_rejects_invalid_iou_threshold(self):
        with pytest.raises(ValueError, match="cooldown_handoff_iou_threshold"):
            FallDetectorConfig(cooldown_handoff_iou_threshold=0.0)
        with pytest.raises(ValueError, match="cooldown_handoff_iou_threshold"):
            FallDetectorConfig(cooldown_handoff_iou_threshold=1.5)

    def test_rejects_non_positive_foot_distance(self):
        with pytest.raises(ValueError, match="cooldown_handoff_max_foot_distance_norm"):
            FallDetectorConfig(cooldown_handoff_max_foot_distance_norm=0.0)
