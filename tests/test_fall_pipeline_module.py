"""src/safety/fall_pipeline.py 테스트.

AuxiliaryFallModel은 실제 YOLO 추론을 하지 않도록 최소 스텁으로 대체한다
(무거운 모델 로딩 없이 FallPipeline의 배선 로직만 검증). 파일명이
test_fall_pipeline.py(FallDetector 행동 시나리오 테스트)와 겹치지 않도록
test_fall_pipeline_module.py로 분리했다.
"""

from __future__ import annotations

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
