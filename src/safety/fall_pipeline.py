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

PR3부터는 외부 접촉 원인 후보 추정(FallCauseAttributor)도 여기서 함께
배선한다. FallDetector가 낙상 판정에 쓰는 이력과 attribution이 쓰는 이력은
완전히 분리돼 있으므로(src/safety/fall_cause_attributor.py 모듈 docstring
참고), 매 프레임 두 곳 모두에 TrackingResult를 갱신해야 한다.
`fall_config_path`를 넘기면 그 파일의 "cause_attribution" 섹션으로
FallCauseAttributorConfig를 로드하고, 넘기지 않으면 dataclass 기본값을
쓴다 — 새 CLI 옵션을 추가하는 대신, 호출자가 이미 갖고 있는
FallDetectorConfig 파일 경로를 그대로 재사용한다.
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
    """AuxiliaryFallModel(선택) + IoU 매칭 + FallDetector + FallCauseAttributor를

    한 번에 묶는다.

    영상(또는 스트림) 하나당 인스턴스 하나를 새로 만든다 — FallDetector가
    Track 상태를 내부에 유지하므로 영상을 건너뛸 때마다 재생성해야 이전
    영상의 상태가 섞이지 않는다 (evaluate_fall.py가 기존에 영상마다
    FallDetector를 새로 만들던 것과 동일한 정책). FallCauseAttributor도
    Track별 근접 이력을 내부에 유지하므로 같은 이유로 영상마다 재생성한다 —
    다른 영상의 근접 이력이 섞이면 완전히 엉뚱한 원인 후보가 나온다. 반면
    auxiliary_model은 무거운 모델 가중치를 담고 있으므로 호출자가 한 번만
    만들어 여러 FallPipeline 인스턴스에서 재사용해야 한다 (ByteTracker/
    PoseTracker와 동일한 재사용 정책).
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

    def process(self, frame: np.ndarray, tracking_result: TrackingResult) -> List[Event]:
        """한 프레임을 처리하고 FALL_SUSPECT Event 목록을 반환한다."""
        model_evidence = self._compute_model_evidence(frame, tracking_result)
        self.cause_attributor.update(tracking_result)
        return self.detector.process(
            tracking_result,
            model_evidence=model_evidence,
            cause_attributor=self.cause_attributor,
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
