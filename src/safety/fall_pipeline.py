"""낙상 보조 모델, Track 매칭, 상태머신과 원인 후보 추정을 한 경로로 묶는다.

실시간 실행과 오프라인 평가가 같은 처리 순서를 공유하도록 한다. 보조 모델이
없거나 비활성화된 경우에는 bbox/Pose 경로만 사용한다. 원인 후보 추정은 낙상
판정과 별도 이력을 사용하므로 매 프레임 함께 갱신한다.
"""

from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np

from src.common.types import Event, TrackingResult
from src.safety.auxiliary_fall_model import AuxiliaryFallModel
from src.safety.fall_cause_attributor import FallCauseAttributor, FallCauseAttributorConfig
from src.safety.fall_detector import FallDetector, FallDetectorConfig
from src.safety.fall_model_matching import FallModelEvidence, match_detections_to_tracks


class FallPipeline:
    """영상별 상태를 관리하는 낙상 처리 파이프라인.

    영상 또는 스트림마다 새 인스턴스를 사용해 Track 이력이 섞이지 않게 한다.
    모델 가중치를 가진 ``auxiliary_model``은 호출자가 여러 인스턴스에서
    재사용할 수 있다.
    """

    def __init__(
        self,
        fps: float,
        detector_config: Optional[FallDetectorConfig] = None,
        auxiliary_model: Optional[AuxiliaryFallModel] = None,
        iou_threshold: float = 0.3,
        fall_config_path: Optional[str] = None,
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

        if fall_config_path is not None:
            cause_attributor_config = FallCauseAttributorConfig.from_file(fall_config_path)
        else:
            cause_attributor_config = FallCauseAttributorConfig()
        self._validate_cause_attribution_window(cause_attributor_config)
        self.cause_attributor = FallCauseAttributor(fps=fps, config=cause_attributor_config)

    def _validate_cause_attribution_window(
        self, cause_attributor_config: FallCauseAttributorConfig
    ) -> None:
        """FallCauseAttributorConfig 자체는 FallDetectorConfig를 모르므로

        (독립 이력 설계, 모듈 docstring 참고) 각 dataclass의 __post_init__만으로는
        history_window_sec/track_grace_sec이 실제로 필요한 만큼 긴지 확인할 수
        없다 — 둘 다 아는 이 지점에서 교차 검증한다. candidate가
        fall_candidate_timeout_sec 근처까지 버티다 confirm되면, lookback
        구간(`[confirm_time - fall_candidate_timeout_sec - lookback_sec,
        confirm_time - fall_candidate_timeout_sec]`)이 이미 history_window_sec/
        track_grace_sec 밖으로 밀려나 있을 수 있다 — 그러면 실제로 근접했던
        후보의 이력이 사라진 뒤라 attribution이 조용히 실패한다.
        """
        if not cause_attributor_config.enabled:
            return

        required_sec = self.detector.config.fall_candidate_timeout_sec + (
            cause_attributor_config.lookback_sec
        )
        if cause_attributor_config.history_window_sec < required_sec:
            raise ValueError(
                "cause_attribution.history_window_sec"
                f"({cause_attributor_config.history_window_sec})가 너무 짧습니다 — "
                f"fall_candidate_timeout_sec({self.detector.config.fall_candidate_timeout_sec}) + "
                f"lookback_sec({cause_attributor_config.lookback_sec}) = {required_sec} 이상이어야 "
                "candidate가 타임아웃 직전까지 버티다 confirm돼도 lookback 구간 이력이 "
                "남아 있습니다."
            )
        if cause_attributor_config.track_grace_sec < required_sec:
            raise ValueError(
                "cause_attribution.track_grace_sec"
                f"({cause_attributor_config.track_grace_sec})가 너무 짧습니다 — "
                f"fall_candidate_timeout_sec({self.detector.config.fall_candidate_timeout_sec}) + "
                f"lookback_sec({cause_attributor_config.lookback_sec}) = {required_sec} 이상이어야 "
                "합니다(history_window_sec와 동일한 이유)."
            )

    def process(
        self,
        frame: np.ndarray,
        tracking_result: TrackingResult,
        diagnostics: Optional[List[dict]] = None,
    ) -> List[Event]:
        """한 프레임을 처리하고 FALL_SUSPECT Event 목록을 반환한다.

        diagnostics: FallDetector.process()로 그대로 전달한다(평가 프로토콜 V2
            진단 필드, Event schema는 건드리지 않는 side-channel).
        """
        model_evidence = self._compute_model_evidence(frame, tracking_result)
        return self.process_with_evidence(tracking_result, model_evidence, diagnostics)

    def process_with_evidence(
        self,
        tracking_result: TrackingResult,
        model_evidence: Optional[Dict[int, FallModelEvidence]],
        diagnostics: Optional[List[dict]] = None,
    ) -> List[Event]:
        """미리 계산한 모델 근거로 실시간 실행과 동일한 상태머신을 실행한다.

        Signal Cache 재생 시 영상 디코딩과 모델 추론 없이 IoU 매칭 임계값과
        상태머신 설정을 반복 평가하는 진입점이다.
        """
        self.cause_attributor.update(tracking_result)
        return self.detector.process(
            tracking_result,
            model_evidence=model_evidence,
            cause_attributor=self.cause_attributor,
            diagnostics=diagnostics,
        )

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
