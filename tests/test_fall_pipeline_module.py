"""src/safety/fall_pipeline.py 테스트.

AuxiliaryFallModel은 실제 YOLO 추론을 하지 않도록 최소 스텁으로 대체한다
(무거운 모델 로딩 없이 FallPipeline의 배선 로직만 검증). 파일명이
test_fall_pipeline.py(FallDetector 행동 시나리오 테스트)와 겹치지 않도록
test_fall_pipeline_module.py로 분리했다.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest

from src.common.types import Track, TrackingResult
from src.safety.auxiliary_fall_model import FallDetection
from src.safety.fall_pipeline import FallPipeline


class _StubAuxiliaryModel:
    """AuxiliaryFallModel과 같은 인터페이스(enabled, infer())를 흉내내는 테스트 더블."""

    def __init__(self, detections_by_call=None, enabled=True):
        self.enabled = enabled
        self._detections_by_call = list(detections_by_call or [])
        self.infer_calls = 0

    def infer(self, frame):
        self.infer_calls += 1
        if self._detections_by_call:
            return self._detections_by_call.pop(0)
        return []


def _tracking_result(frame_number, bbox, track_id=1) -> TrackingResult:
    tracks = []
    if bbox is not None:
        tracks.append(
            Track(
                track_id=track_id,
                bbox=list(bbox),
                foot_point=[(bbox[0] + bbox[2]) / 2.0, bbox[3]],
                confidence=0.9,
            )
        )
    return TrackingResult(
        frame_number=frame_number,
        timestamp="00:00:00.000",
        video_source="cam1",
        tracks=tracks,
    )


_BBOX = (0.0, 0.0, 10.0, 10.0)
_FRAME = np.zeros((32, 32, 3), dtype=np.uint8)


class TestFallPipelineIouThresholdValidation:
    def test_zero_iou_threshold_rejected_at_construction(self):
        with pytest.raises(ValueError, match="iou_threshold"):
            FallPipeline(fps=10.0, iou_threshold=0.0)

    def test_negative_or_above_one_iou_threshold_rejected_at_construction(self):
        with pytest.raises(ValueError, match="iou_threshold"):
            FallPipeline(fps=10.0, iou_threshold=-0.1)
        with pytest.raises(ValueError, match="iou_threshold"):
            FallPipeline(fps=10.0, iou_threshold=1.1)


class TestAuxiliaryInferenceInterval:
    @pytest.mark.parametrize("value", [0, -1, 1.5, True])
    def test_rejects_invalid_interval(self, value):
        with pytest.raises(ValueError, match="auxiliary_inference_interval_frames"):
            FallPipeline(fps=10.0, auxiliary_inference_interval_frames=value)

    def test_default_interval_runs_model_every_frame_with_tracks(self):
        stub = _StubAuxiliaryModel(detections_by_call=[[], [], []])
        pipeline = FallPipeline(fps=10.0, auxiliary_model=stub)

        for frame_number in range(3):
            pipeline.process(_FRAME, _tracking_result(frame_number, _BBOX))

        assert stub.infer_calls == 3

    def test_interval_runs_only_scheduled_frames(self):
        stub = _StubAuxiliaryModel(detections_by_call=[[], []])
        pipeline = FallPipeline(
            fps=10.0,
            auxiliary_model=stub,
            auxiliary_inference_interval_frames=3,
        )

        for frame_number in range(6):
            pipeline.process(_FRAME, _tracking_result(frame_number, _BBOX))

        assert stub.infer_calls == 2  # frame 0, 3

    def test_skipped_frame_reuses_last_evidence_for_same_track(self):
        fall_detection = [FallDetection(bbox=list(_BBOX), label="fall", confidence=0.9)]
        stub = _StubAuxiliaryModel(detections_by_call=[fall_detection])
        pipeline = FallPipeline(
            fps=10.0,
            auxiliary_model=stub,
            auxiliary_inference_interval_frames=3,
        )
        pipeline.detector.process = MagicMock(return_value=[])

        pipeline.process(_FRAME, _tracking_result(0, _BBOX, track_id=1))
        pipeline.process(_FRAME, _tracking_result(1, _BBOX, track_id=1))

        _, kwargs = pipeline.detector.process.call_args
        assert kwargs["model_evidence"][1].label == "fall"
        assert stub.infer_calls == 1

    def test_skipped_frame_does_not_reuse_evidence_for_new_track(self):
        fall_detection = [FallDetection(bbox=list(_BBOX), label="fall", confidence=0.9)]
        stub = _StubAuxiliaryModel(detections_by_call=[fall_detection])
        pipeline = FallPipeline(
            fps=10.0,
            auxiliary_model=stub,
            auxiliary_inference_interval_frames=3,
        )
        pipeline.detector.process = MagicMock(return_value=[])

        pipeline.process(_FRAME, _tracking_result(0, _BBOX, track_id=1))
        pipeline.process(_FRAME, _tracking_result(1, _BBOX, track_id=2))

        _, kwargs = pipeline.detector.process.call_args
        assert kwargs["model_evidence"][2].label == "unknown"
        assert 1 not in kwargs["model_evidence"]

    def test_no_tracks_never_runs_model_even_on_scheduled_frame(self):
        stub = _StubAuxiliaryModel(detections_by_call=[[]])
        pipeline = FallPipeline(
            fps=10.0,
            auxiliary_model=stub,
            auxiliary_inference_interval_frames=3,
        )

        pipeline.process(_FRAME, _tracking_result(0, None))

        assert stub.infer_calls == 0


class TestPoseNormalGate:
    def test_requires_enabled_auxiliary_model(self):
        with pytest.raises(ValueError, match="requires an enabled auxiliary"):
            FallPipeline(
                fps=10.0,
                pose_normal_gate=MagicMock(),
            )

    def test_confident_normal_skips_auxiliary_model(self):
        gate = MagicMock()
        gate.evaluate.return_value = SimpleNamespace(use_auxiliary=False)
        stub = _StubAuxiliaryModel()
        pipeline = FallPipeline(
            fps=10.0,
            auxiliary_model=stub,
            pose_normal_gate=gate,
            auxiliary_inference_interval_frames=3,
        )
        pipeline.detector.process = MagicMock(return_value=[])

        pipeline.process(_FRAME, _tracking_result(8, _BBOX))

        assert stub.infer_calls == 0
        _, kwargs = pipeline.detector.process.call_args
        assert kwargs["model_evidence"][1].label == "nofall"

    def test_fallback_runs_immediately_then_holds_until_interval(self):
        gate = MagicMock()
        gate.evaluate.return_value = SimpleNamespace(use_auxiliary=True)
        fall_detection = [
            FallDetection(bbox=list(_BBOX), label="fall", confidence=0.9)
        ]
        stub = _StubAuxiliaryModel(
            detections_by_call=[fall_detection, fall_detection]
        )
        pipeline = FallPipeline(
            fps=10.0,
            auxiliary_model=stub,
            pose_normal_gate=gate,
            auxiliary_inference_interval_frames=3,
        )
        pipeline.detector.process = MagicMock(return_value=[])

        for frame_number in range(4):
            pipeline.process(_FRAME, _tracking_result(frame_number, _BBOX))

        assert stub.infer_calls == 2  # fallback entry frame 0, refresh frame 3

    def test_fallback_after_normal_route_does_not_wait_for_interval(self):
        gate = MagicMock()
        gate.evaluate.side_effect = [
            SimpleNamespace(use_auxiliary=False),
            SimpleNamespace(use_auxiliary=True),
        ]
        stub = _StubAuxiliaryModel(detections_by_call=[[]])
        pipeline = FallPipeline(
            fps=10.0,
            auxiliary_model=stub,
            pose_normal_gate=gate,
            auxiliary_inference_interval_frames=3,
        )

        pipeline.process(_FRAME, _tracking_result(10, _BBOX))
        pipeline.process(_FRAME, _tracking_result(11, _BBOX))

        assert stub.infer_calls == 1


class TestFallPipelineWithoutAuxiliaryModel:
    def test_no_auxiliary_model_behaves_like_bbox_only_detector(self):
        pipeline = FallPipeline(fps=10.0, auxiliary_model=None)

        events = pipeline.process(_FRAME, _tracking_result(0, _BBOX))

        assert events == []  # 예외 없이, 모델 없이 정상 동작해야 함

    def test_disabled_auxiliary_model_skips_inference(self):
        stub = _StubAuxiliaryModel(enabled=False)
        pipeline = FallPipeline(fps=10.0, auxiliary_model=stub)

        pipeline.process(_FRAME, _tracking_result(0, _BBOX))

        assert stub.infer_calls == 0  # enabled=False면 infer()를 호출조차 하지 않아야 함


class TestFallPipelineWithAuxiliaryModel:
    def test_matched_fall_evidence_reaches_detector_without_error(self):
        stub = _StubAuxiliaryModel(
            detections_by_call=[[FallDetection(bbox=list(_BBOX), label="fall", confidence=0.9)]]
        )
        pipeline = FallPipeline(fps=10.0, auxiliary_model=stub, iou_threshold=0.3)

        events = pipeline.process(_FRAME, _tracking_result(0, _BBOX))

        assert stub.infer_calls == 1
        assert events == []  # 첫 프레임은 아직 candidate 진입 조건(동적 근거)이 없음

    def test_no_tracks_returns_empty_evidence_without_calling_model(self):
        """Track이 없으면 매칭할 대상이 없으므로 모델 추론 자체를 부르지 않는다."""
        stub = _StubAuxiliaryModel(detections_by_call=[[]])
        pipeline = FallPipeline(fps=10.0, auxiliary_model=stub)

        events = pipeline.process(_FRAME, _tracking_result(0, None))

        assert events == []
        assert stub.infer_calls == 0

    def test_reuses_same_auxiliary_model_across_multiple_pipelines(self):
        """auxiliary_model은 영상마다 새로 만들지 않고 재사용해야 한다 (무거운 가중치)."""
        stub = _StubAuxiliaryModel(detections_by_call=[[], []])

        pipeline_a = FallPipeline(fps=10.0, auxiliary_model=stub)
        pipeline_b = FallPipeline(fps=10.0, auxiliary_model=stub)

        pipeline_a.process(_FRAME, _tracking_result(0, _BBOX))
        pipeline_b.process(_FRAME, _tracking_result(0, _BBOX))

        assert pipeline_a.auxiliary_model is pipeline_b.auxiliary_model
        assert stub.infer_calls == 2


class TestProcessWithEvidence:
    """Signal Cache 재생 경로가 쓰는 frame-독립 진입점.

    process()는 frame에서 model_evidence를 계산한 뒤 이 메서드를 호출하는
    얇은 wrapper가 됐다 — 여기서는 그 model_evidence를 캐시에서 미리
    IoU 매칭해 직접 넘겨도 process()와 동일하게 동작하는지 확인한다.
    """

    def test_process_with_evidence_matches_process_result_for_same_evidence(self):
        """process(frame, ...)와 process_with_evidence(..., 동일 model_evidence)가

        같은 이벤트를 내야 한다 — process()가 내부적으로 이 메서드를
        재사용한다는 걸 행동으로 검증한다.
        """
        from src.safety.fall_model_matching import FallModelEvidence

        stub = _StubAuxiliaryModel(
            detections_by_call=[[FallDetection(bbox=list(_BBOX), label="fall", confidence=0.9)]]
        )
        pipeline_a = FallPipeline(fps=10.0, auxiliary_model=stub, iou_threshold=0.3)
        pipeline_b = FallPipeline(fps=10.0, iou_threshold=0.3)

        tracking_result = _tracking_result(0, _BBOX)
        events_a = pipeline_a.process(_FRAME, tracking_result)
        events_b = pipeline_b.process_with_evidence(
            tracking_result,
            {1: FallModelEvidence(track_id=1, label="fall", confidence=0.9, iou=1.0)},
        )

        assert [e.event_type for e in events_a] == [e.event_type for e in events_b]

    def test_process_with_evidence_none_disables_model_path(self):
        pipeline = FallPipeline(fps=10.0)
        events = pipeline.process_with_evidence(_tracking_result(0, _BBOX), None)
        assert events == []  # 동적 근거 없는 첫 프레임 + model 비활성 -> candidate조차 진입 안 함

    def test_process_with_evidence_updates_cause_attributor(self):
        """process()와 마찬가지로 매 호출마다 cause_attributor.update()가 불려야

        원인 후보 추정이 캐시 재생 경로에서도 그대로 동작한다.
        """
        pipeline = FallPipeline(fps=10.0)
        tracking_result = _tracking_result(0, _BBOX)

        pipeline.process_with_evidence(tracking_result, None)

        history = pipeline.cause_attributor._history.get((tracking_result.video_source, 1))
        assert len(history) == 1


class TestFallPipelineEndToEndConfirmation:
    """AuxiliaryFallModel이 지속적으로 fall을 반환하면 실제로 FALL_SUSPECT까지

    이어지는지 확인한다 (매칭 -> FallDetector 통합이 실제로 동작하는지).
    """

    _STANDING_BBOX = (40.0, 0.0, 60.0, 60.0)
    _NON_HORIZONTAL_BBOX = (40.0, 20.0, 60.0, 80.0)

    def test_sustained_fall_detection_confirms_through_pipeline(self):
        from src.safety.fall_detector import FallDetectorConfig

        config = FallDetectorConfig(cooldown_sec=1.0)
        # 매 프레임 같은 bbox의 fall detection을 반환하는 스텁 (IoU=1.0으로 항상 매칭됨)
        fall_detection = [
            FallDetection(bbox=list(self._NON_HORIZONTAL_BBOX), label="fall", confidence=0.9)
        ]
        stub = _StubAuxiliaryModel(detections_by_call=[fall_detection for _ in range(20)])
        pipeline = FallPipeline(fps=10.0, detector_config=config, auxiliary_model=stub)

        events = []
        for frame_number in range(5):
            events += pipeline.process(_FRAME, _tracking_result(frame_number, self._STANDING_BBOX))
        for frame_number in range(5, 15):
            events += pipeline.process(
                _FRAME, _tracking_result(frame_number, self._NON_HORIZONTAL_BBOX)
            )

        assert len(events) == 1
        assert events[0].event_type == "FALL_SUSPECT"


class TestFallPipelineCauseAttributorWiring:
    """FallCauseAttributor 자체의 후보 탐색·점수 계산은

    tests/test_fall_cause_attributor.py에서 이미 검증했다. 여기서는
    FallPipeline이 그 인스턴스를 올바르게 만들고(fall_config_path 로딩
    포함) 매 프레임 update()를 호출하는지만 배선 관점에서 확인한다.
    """

    def test_cause_attributor_created_with_default_config_when_no_path_given(self):
        pipeline = FallPipeline(fps=10.0)

        assert pipeline.cause_attributor is not None
        assert pipeline.cause_attributor.config.enabled is True

    def test_fall_config_path_loads_cause_attribution_section(self):
        pipeline = FallPipeline(fps=10.0, fall_config_path="configs/fall_detection.json")

        assert pipeline.cause_attributor.config.lookback_sec == 1.0
        assert pipeline.cause_attributor.config.history_window_sec == 4.0
        assert pipeline.cause_attributor.config.track_grace_sec == 4.0
        assert pipeline.cause_attributor.config.max_pairing_gap_frames == 1.5

    def test_fall_config_path_actually_reads_non_default_values(self, tmp_path):
        """configs/fall_detection.json의 값이 우연히 dataclass 기본값과 같아서

        "읽었다"는 착각을 주지 않도록, 기본값과 다른 값을 넣은 임시 설정
        파일로 실제 파일을 읽는지 확인한다.
        """
        import json

        custom_config = tmp_path / "custom_fall_detection.json"
        custom_config.write_text(
            json.dumps(
                {
                    "cause_attribution": {
                        "enabled": False,
                        "lookback_sec": 2.5,
                        "history_window_sec": 9.0,
                        "track_grace_sec": 9.0,
                        "score_threshold": 0.9,
                        "max_pairing_gap_frames": 3.0,
                    }
                }
            ),
            encoding="utf-8",
        )

        pipeline = FallPipeline(fps=10.0, fall_config_path=str(custom_config))

        assert pipeline.cause_attributor.config.enabled is False
        assert pipeline.cause_attributor.config.lookback_sec == 2.5
        assert pipeline.cause_attributor.config.history_window_sec == 9.0
        assert pipeline.cause_attributor.config.track_grace_sec == 9.0
        assert pipeline.cause_attributor.config.score_threshold == 0.9
        assert pipeline.cause_attributor.config.max_pairing_gap_frames == 3.0

    def test_cause_attributor_history_grows_every_frame(self):
        """update()가 매 프레임 호출되는지, FallDetector.process()보다 먼저

        호출돼도 문제없는지 간접 확인한다 (같은 프레임 데이터가 이력에 반영됨).
        """
        pipeline = FallPipeline(fps=10.0, auxiliary_model=None)

        for frame_number in range(3):
            pipeline.process(_FRAME, _tracking_result(frame_number, _BBOX))

        history = pipeline.cause_attributor._history[("cam1", 1)]
        assert len(history) == 3


class TestCauseAttributionWindowCrossValidation:
    """FallCauseAttributorConfig와 FallDetectorConfig는 서로 독립된

    dataclass라 각자의 __post_init__만으로는 history_window_sec/
    track_grace_sec이 fall_candidate_timeout_sec + lookback_sec을
    덮는지 확인할 수 없다 — 둘 다 아는 FallPipeline 생성 시점에서
    교차 검증돼야 한다.
    """

    def _write_config(self, tmp_path, **cause_overrides):
        import json

        from src.safety.fall_detector import FallDetectorConfig

        config_path = tmp_path / "fall_detection.json"
        config_path.write_text(
            json.dumps({"cause_attribution": cause_overrides}), encoding="utf-8"
        )
        return str(config_path), FallDetectorConfig(fall_candidate_timeout_sec=2.0)

    def test_rejects_history_window_shorter_than_timeout_plus_lookback(self, tmp_path):
        config_path, detector_config = self._write_config(
            tmp_path,
            lookback_sec=1.0,
            history_window_sec=2.5,  # 필요치(2.0+1.0=3.0) 미달
            track_grace_sec=4.0,
        )

        with pytest.raises(ValueError, match="history_window_sec"):
            FallPipeline(
                fps=10.0, detector_config=detector_config, fall_config_path=config_path
            )

    def test_rejects_track_grace_shorter_than_timeout_plus_lookback(self, tmp_path):
        config_path, detector_config = self._write_config(
            tmp_path,
            lookback_sec=1.0,
            history_window_sec=4.0,
            track_grace_sec=2.5,  # 필요치(2.0+1.0=3.0) 미달
        )

        with pytest.raises(ValueError, match="track_grace_sec"):
            FallPipeline(
                fps=10.0, detector_config=detector_config, fall_config_path=config_path
            )

    def test_accepts_exactly_sufficient_window(self, tmp_path):
        config_path, detector_config = self._write_config(
            tmp_path,
            lookback_sec=1.0,
            history_window_sec=3.0,  # 정확히 필요치
            track_grace_sec=3.0,
        )

        FallPipeline(
            fps=10.0, detector_config=detector_config, fall_config_path=config_path
        )  # 예외 없이 생성돼야 함

    def test_disabled_attribution_skips_cross_validation(self, tmp_path):
        """enabled=False면 attribution이 아예 동작하지 않으므로, window가

        짧아도 검증에서 걸러지면 안 된다 (불필요한 제약이 된다).
        """
        config_path, detector_config = self._write_config(
            tmp_path,
            enabled=False,
            lookback_sec=1.0,
            history_window_sec=1.5,  # 필요치 미달이지만 enabled=False라 무관
            track_grace_sec=1.5,
        )

        FallPipeline(
            fps=10.0, detector_config=detector_config, fall_config_path=config_path
        )  # 예외 없이 생성돼야 함


class TestFallPipelineCauseAttributionEndToEnd:
    """모델 confirm 경로로 낙상이 확정될 때, 실제로 근접·접근 중이던 다른

    Track이 cause=NEARBY_TRACK으로 기록되는지 FallCauseAttributor·
    FallDetector·FallPipeline을 전부 실제로 연결해 검증한다 (mock은
    AuxiliaryFallModel뿐 — cause attribution 경로는 전부 실제 코드다).

    victim은 TestFallPipelineEndToEndConfirmation과 동일한 bbox 쌍을 쓴다.
    이 조합은 매 프레임 동일한 위치의 FallDetection과 IoU 매칭되어 이미
    STANDING 구간(frame 0~2)부터 모델 근거가 쌓이기 시작해 frame 3(t=0.3초)
    에 candidate 진입, frame 4(t=0.4초)에 바로 confirm된다 — 순서가 빠르므로
    candidate(접근하는 Track)도 이 짧은 lookback 구간(0.0~0.3초) 안에서
    확실히 가까워지도록 설계했다.
    """

    _STANDING_BBOX = (40.0, 0.0, 60.0, 60.0)
    _NON_HORIZONTAL_BBOX = (40.0, 20.0, 60.0, 80.0)

    def _victim_bbox(self, frame_number: int) -> tuple:
        return self._STANDING_BBOX if frame_number < 5 else self._NON_HORIZONTAL_BBOX

    def _make_stub_model(self, num_frames: int = 15) -> _StubAuxiliaryModel:
        fall_detection = [
            FallDetection(bbox=list(self._NON_HORIZONTAL_BBOX), label="fall", confidence=0.9)
        ]
        return _StubAuxiliaryModel(detections_by_call=[fall_detection for _ in range(num_frames)])

    def _approaching_candidate_bbox(self, frame_number: int) -> tuple:
        """t=0.0(cx=200, 멀리)에서 t=0.3(cx=75, victim 근처)까지 접근한 뒤 정지한다.

        confirm이 t=0.4초에 일어나고 fall_start_sec(candidate 진입 시각)은
        t=0.3초이므로, lookback 구간(기본 1.0초)이 사실상 [0.0, 0.3]이다.
        y범위(20~80)는 victim의 NON_HORIZONTAL_BBOX와 맞춰 같은 '바닥 높이'를
        흉내내되, x범위는 victim의 bbox(40~60)·AuxiliaryFallModel detection
        (40~60)과 항상 5px 이상 떨어뜨려 IoU 매칭이나 자체 낙상 오판정과
        절대 얽히지 않게 한다.
        """
        t = frame_number / 10.0
        progress = min(t / 0.3, 1.0)
        cx = 200.0 - (200.0 - 75.0) * progress
        return (cx - 10.0, 20.0, cx + 10.0, 80.0)

    def _multi_track_result(self, frame_number: int, candidate_bbox: tuple) -> TrackingResult:
        victim_bbox = self._victim_bbox(frame_number)
        return TrackingResult(
            frame_number=frame_number,
            timestamp="00:00:00.000",
            video_source="cam1",
            tracks=[
                Track(
                    track_id=1,
                    bbox=list(victim_bbox),
                    foot_point=[(victim_bbox[0] + victim_bbox[2]) / 2.0, victim_bbox[3]],
                    confidence=0.9,
                ),
                Track(
                    track_id=2,
                    bbox=list(candidate_bbox),
                    foot_point=[
                        (candidate_bbox[0] + candidate_bbox[2]) / 2.0,
                        candidate_bbox[3],
                    ],
                    confidence=0.9,
                ),
            ],
        )

    def test_approaching_track_becomes_cause_of_confirmed_fall(self):
        from src.safety.fall_detector import FallDetectorConfig

        config = FallDetectorConfig(cooldown_sec=1.0)
        pipeline = FallPipeline(
            fps=10.0, detector_config=config, auxiliary_model=self._make_stub_model()
        )

        events = []
        for frame_number in range(15):
            candidate_bbox = self._approaching_candidate_bbox(frame_number)
            events += pipeline.process(
                _FRAME, self._multi_track_result(frame_number, candidate_bbox)
            )

        assert len(events) == 1
        event = events[0]
        assert event.event_type == "FALL_SUSPECT"
        assert event.track_id == 1
        assert event.cause is not None
        assert event.cause.type == "NEARBY_TRACK"
        assert event.cause.track_id == 2
        assert 0.0 < event.cause.score <= 1.0

    def test_stationary_far_track_does_not_become_cause(self):
        """후보가 접근하지 않고 계속 멀리 있으면 cause=null이어야 한다."""
        from src.safety.fall_detector import FallDetectorConfig

        config = FallDetectorConfig(cooldown_sec=1.0)
        pipeline = FallPipeline(
            fps=10.0, detector_config=config, auxiliary_model=self._make_stub_model()
        )
        far_candidate_bbox = (500.0, 20.0, 520.0, 80.0)  # 계속 멀리, 접근 없음

        events = []
        for frame_number in range(15):
            events += pipeline.process(
                _FRAME, self._multi_track_result(frame_number, far_candidate_bbox)
            )

        assert len(events) == 1
        assert events[0].cause is None


class TestCauseAttributionSurvivesDelayedConfirm:
    """candidate가 fall_candidate_timeout_sec에 가깝게 오래 머물다 confirm돼도

    (모델 근거 없이 순수 bbox 수평 자세 지속만으로), 교차 검증을 통과하는
    history_window_sec/track_grace_sec이면 lookback 구간의 후보 이력이
    evict되지 않고 여전히 attribution에 쓰일 수 있어야 한다.
    """

    _STANDING_BBOX = (40.0, 0.0, 60.0, 60.0)
    _LYING_BBOX = (10.0, 50.0, 90.0, 70.0)

    def _victim_result(self, frame_number: int) -> TrackingResult:
        bbox = self._STANDING_BBOX if frame_number < 5 else self._LYING_BBOX
        tracks = [
            Track(
                track_id=1,
                bbox=list(bbox),
                foot_point=[(bbox[0] + bbox[2]) / 2.0, bbox[3]],
                confidence=0.9,
            )
        ]
        return TrackingResult(
            frame_number=frame_number, timestamp="00:00:00.000", video_source="cam1",
            tracks=tracks,
        )

    def _multi_result(self, frame_number: int, candidate_cx: float) -> TrackingResult:
        result = self._victim_result(frame_number)
        candidate_bbox = (candidate_cx - 10.0, 0.0, candidate_cx + 10.0, 60.0)
        result.tracks.append(
            Track(
                track_id=2,
                bbox=list(candidate_bbox),
                foot_point=[candidate_cx, 60.0],
                confidence=0.9,
            )
        )
        return result

    def test_cause_still_found_when_confirm_is_delayed_near_timeout(self, tmp_path):
        import json

        from src.safety.fall_detector import FallDetectorConfig

        # candidate 진입(t=0.5) 후 fall_confirm_sec(1.5초)만큼 수평 자세가
        # 지속돼야 confirm된다(t=2.0) — fall_candidate_timeout_sec(1.8초)
        # 이내라 타임아웃 전에 confirm되지만, candidate 진입 시각과 confirm
        # 시각 사이의 간격(1.5초)이 짧지 않다.
        detector_config = FallDetectorConfig(
            cooldown_sec=1.0, fall_confirm_sec=1.5, fall_candidate_timeout_sec=1.8
        )
        # 필요 최소치(1.8+0.5=2.3)를 충족하는 값으로 설정.
        config_path = tmp_path / "fall_detection.json"
        config_path.write_text(
            json.dumps(
                {
                    "cause_attribution": {
                        "enabled": True,
                        "lookback_sec": 0.5,
                        "history_window_sec": 2.3,
                        "track_grace_sec": 2.5,
                        "min_samples": 2,
                        "distance_threshold": 1.5,
                        "closing_speed_threshold": 1.0,
                        "min_closing_speed_norm": 0.1,
                        "distance_weight": 0.5,
                        "speed_weight": 0.5,
                        "score_threshold": 0.5,
                    }
                }
            ),
            encoding="utf-8",
        )
        pipeline = FallPipeline(
            fps=10.0,
            detector_config=detector_config,
            auxiliary_model=None,
            fall_config_path=str(config_path),
        )

        events = []
        for frame_number in range(30):
            t = frame_number / 10.0
            if t <= 0.5:
                # candidate가 lookback 구간(0.0~0.5초) 동안만 victim에게
                # 접근한 뒤, 그 이후로는 화면에서 완전히 사라진다.
                progress = t / 0.5
                candidate_cx = 200.0 - (200.0 - 75.0) * progress
                events += pipeline.process(_FRAME, self._multi_result(frame_number, candidate_cx))
            else:
                events += pipeline.process(_FRAME, self._victim_result(frame_number))

        assert len(events) == 1
        assert events[0].cause is not None
        assert events[0].cause.track_id == 2
