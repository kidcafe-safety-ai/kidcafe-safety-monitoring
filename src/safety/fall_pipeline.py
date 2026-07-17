"""frame + TrackingResult -> 보조 fall/nofall 모델 추론 -> Track IoU 매칭 ->

FallDetector.process() 순서를 하나로 묶는다.

이 모듈이 없으면 `main.py`(실제 서비스 실행)와 `scripts/evaluate_fall.py`
(오프라인 평가)가 "보조 모델 추론 → IoU 매칭 → FallDetector.process() 호출"
순서를 각자 복사해야 한다. 그러면 실제 실행과 평가가 서로 다른 로직을 타게
될 위험이 생기고(둘 중 하나만 고치는 실수), 매칭 관련 버그를 두 곳에서 각각
고쳐야 한다. FallPipeline 하나로 두 호출자가 정확히 같은 로직을 공유한다.

AuxiliaryFallModel을 아예 넘기지 않거나 enabled=False면 보조 모델 추론
자체를 건너뛰고 FallDetector.process()에 model_evidence=None을 전달한다 —
기존 bbox/pose 전용 동작과 완전히 하위 호환된다 (src/safety/fall_detector.py
모듈 docstring 참고).
"""

from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np

from src.common.types import Event, TrackingResult
from src.safety.auxiliary_fall_model import AuxiliaryFallModel
from src.safety.fall_detector import FallDetector, FallDetectorConfig
from src.safety.fall_model_matching import FallModelEvidence, match_detections_to_tracks


class FallPipeline:
    """AuxiliaryFallModel(선택) + IoU 매칭 + FallDetector를 한 번에 묶는다.

    영상(또는 스트림) 하나당 인스턴스 하나를 새로 만든다 — FallDetector가
    Track 상태를 내부에 유지하므로 영상을 건너뛸 때마다 재생성해야 이전
    영상의 상태가 섞이지 않는다 (evaluate_fall.py가 기존에 영상마다
    FallDetector를 새로 만들던 것과 동일한 정책). 반면 auxiliary_model은
    무거운 모델 가중치를 담고 있으므로 호출자가 한 번만 만들어 여러
    FallPipeline 인스턴스에서 재사용해야 한다 (ByteTracker/PoseTracker와
    동일한 재사용 정책).
    """

    def __init__(
        self,
        fps: float,
        detector_config: Optional[FallDetectorConfig] = None,
        auxiliary_model: Optional[AuxiliaryFallModel] = None,
        iou_threshold: float = 0.3,
    ):
        if not (0.0 < iou_threshold <= 1.0):
            raise ValueError(
                f"iou_threshold는 0보다 크고 1 이하여야 합니다: {iou_threshold} "
                "(match_detections_to_tracks와 동일한 계약, 0을 허용하면 전혀 "
                "겹치지 않는 bbox끼리도 매칭됩니다)"
            )
        self.detector = FallDetector(fps=fps, config=detector_config)
        self.auxiliary_model = auxiliary_model
        self.iou_threshold = iou_threshold

    def process(self, frame: np.ndarray, tracking_result: TrackingResult) -> List[Event]:
        """한 프레임을 처리하고 FALL_SUSPECT Event 목록을 반환한다."""
        model_evidence = self._compute_model_evidence(frame, tracking_result)
        return self.detector.process(tracking_result, model_evidence=model_evidence)

    def _compute_model_evidence(
        self, frame: np.ndarray, tracking_result: TrackingResult
    ) -> Optional[Dict[int, FallModelEvidence]]:
        if self.auxiliary_model is None or not self.auxiliary_model.enabled:
            return None
        if not tracking_result.tracks:
            # Track이 없으면 매칭할 대상도 없다. 빈 딕셔너리를 반환한다 —
            # None(모델 완전 비활성화)과는 의미가 다르다: 모델은 켜져 있지만
            # 이번 프레임엔 매칭할 Track이 없었을 뿐이다.
            return {}
        detections = self.auxiliary_model.infer(frame)
        evidence_list = match_detections_to_tracks(
            tracking_result.tracks, detections, self.iou_threshold
        )
        return {evidence.track_id: evidence for evidence in evidence_list}
