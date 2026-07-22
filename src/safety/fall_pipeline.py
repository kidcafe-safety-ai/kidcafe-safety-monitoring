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
from src.safety.pose_normal_gate import PoseNormalGate


def validate_auxiliary_inference_interval_frames(interval_frames: int) -> None:
    """보조 모델 추론 간격이 양의 정수인지 검증한다."""
    if (
        isinstance(interval_frames, bool)
        or not isinstance(interval_frames, int)
        or interval_frames <= 0
    ):
        raise ValueError(
            "auxiliary_inference_interval_frames는 0보다 큰 정수여야 합니다: "
            f"{interval_frames!r}"
        )


def should_run_auxiliary_inference(frame_number: int, interval_frames: int) -> bool:
    """고정 간격 스케줄에서 현재 프레임이 보조 모델 실행 대상인지 반환한다."""
    validate_auxiliary_inference_interval_frames(interval_frames)
    return frame_number % interval_frames == 0


class AuxiliaryEvidenceCadence:
    """고정 간격 추론 사이에서 마지막 Track별 모델 판단을 짧게 유지한다.

    interval_frames=1이면 모든 frame이 fresh inference 대상이라 기존 동작과
    동일하다. 건너뛴 frame에서는 같은 track_id의 직전 판단만 재사용하며,
    새 track_id는 unknown으로 시작한다. 다음 scheduled frame에서는 fresh
    evidence로 전체 active Track 상태를 교체하므로 hold 상한은 최대
    interval_frames-1 frame이다.
    """

    def __init__(self, interval_frames: int = 1):
        validate_auxiliary_inference_interval_frames(interval_frames)
        self.interval_frames = interval_frames
        self._last_evidence: Dict[int, FallModelEvidence] = {}

    def should_infer(self, frame_number: int) -> bool:
        return should_run_auxiliary_inference(frame_number, self.interval_frames)

    def reset(self) -> None:
        self._last_evidence = {}

    def resolve(
        self,
        tracking_result: TrackingResult,
        fresh_evidence: Optional[Dict[int, FallModelEvidence]],
    ) -> Dict[int, FallModelEvidence]:
        """fresh evidence를 저장하거나, skipped frame이면 같은 Track 판단을 유지한다."""
        resolved: Dict[int, FallModelEvidence] = {}
        source = self._last_evidence if fresh_evidence is None else fresh_evidence
        for track in tracking_result.tracks:
            evidence = source.get(track.track_id)
            if evidence is None:
                evidence = FallModelEvidence(
                    track_id=track.track_id,
                    label="unknown",
                    confidence=None,
                    iou=None,
                )
            resolved[track.track_id] = evidence

        # 소실된 Track의 판단은 즉시 버려 새 Track에 잘못 재사용되지 않게 한다.
        self._last_evidence = resolved
        return resolved


class AdaptiveAuxiliaryInferenceCadence:
    """Run immediately on fallback entry/new Track, then at a bounded interval."""

    def __init__(self, interval_frames: int):
        validate_auxiliary_inference_interval_frames(interval_frames)
        self.interval_frames = interval_frames
        self.reset()

    def reset(self) -> None:
        self._in_fallback = False
        self._last_inference_frame: Optional[int] = None
        self._known_track_ids: set[int] = set()

    def should_infer(
        self, tracking_result: TrackingResult, use_auxiliary: bool
    ) -> bool:
        active_track_ids = {track.track_id for track in tracking_result.tracks}
        if not active_track_ids or not use_auxiliary:
            self.reset()
            return False

        new_track = not active_track_ids.issubset(self._known_track_ids)
        interval_elapsed = (
            self._last_inference_frame is None
            or tracking_result.frame_number - self._last_inference_frame
            >= self.interval_frames
        )
        should_infer = not self._in_fallback or new_track or interval_elapsed
        self._in_fallback = True
        self._known_track_ids = active_track_ids
        if should_infer:
            self._last_inference_frame = tracking_result.frame_number
        return should_infer


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
        auxiliary_inference_interval_frames: int = 1,
        pose_normal_gate: Optional[PoseNormalGate] = None,
    ):
        if not (0.0 < iou_threshold <= 1.0):
            raise ValueError(
                f"iou_threshold는 0보다 크고 1 이하여야 합니다: {iou_threshold} "
                "(match_detections_to_tracks와 동일한 계약, 0을 허용하면 전혀 "
                "겹치지 않는 bbox끼리도 매칭됩니다)"
            )
        validate_auxiliary_inference_interval_frames(
            auxiliary_inference_interval_frames
        )
        self.detector = FallDetector(fps=fps, config=detector_config)
        self.auxiliary_model = auxiliary_model
        self.iou_threshold = iou_threshold
        self.auxiliary_inference_interval_frames = auxiliary_inference_interval_frames
        self.pose_normal_gate = pose_normal_gate
        if pose_normal_gate is not None and (
            auxiliary_model is None or not auxiliary_model.enabled
        ):
            raise ValueError(
                "pose normal gate requires an enabled auxiliary fall model"
            )
        self._auxiliary_evidence_cadence = AuxiliaryEvidenceCadence(
            auxiliary_inference_interval_frames
        )
        self._adaptive_inference_cadence = AdaptiveAuxiliaryInferenceCadence(
            auxiliary_inference_interval_frames
        )

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
        if self.pose_normal_gate is not None:
            return self._compute_pose_gated_evidence(frame, tracking_result)
        if not tracking_result.tracks:
            # Track이 없으면 매칭할 대상도 없다. 빈 딕셔너리를 반환한다 —
            # None(모델 완전 비활성화)과는 의미가 다르다: 모델은 켜져 있지만
            # 이번 프레임엔 매칭할 Track이 없었을 뿐이다.
            return self._auxiliary_evidence_cadence.resolve(tracking_result, {})
        if not self._auxiliary_evidence_cadence.should_infer(
            tracking_result.frame_number
        ):
            return self._auxiliary_evidence_cadence.resolve(tracking_result, None)
        detections = self.auxiliary_model.infer(frame)
        evidence_list = match_detections_to_tracks(
            tracking_result.tracks, detections, self.iou_threshold
        )
        fresh_evidence = {evidence.track_id: evidence for evidence in evidence_list}
        return self._auxiliary_evidence_cadence.resolve(tracking_result, fresh_evidence)

    def _compute_pose_gated_evidence(
        self, frame: np.ndarray, tracking_result: TrackingResult
    ) -> Dict[int, FallModelEvidence]:
        decision = self.pose_normal_gate.evaluate(tracking_result)
        if not decision.use_auxiliary:
            self._adaptive_inference_cadence.should_infer(
                tracking_result, use_auxiliary=False
            )
            self._auxiliary_evidence_cadence.reset()
            return {
                track.track_id: FallModelEvidence(
                    track_id=track.track_id,
                    label="nofall",
                    confidence=track.confidence,
                    iou=1.0,
                )
                for track in tracking_result.tracks
            }

        should_infer = self._adaptive_inference_cadence.should_infer(
            tracking_result, use_auxiliary=True
        )
        if not should_infer:
            return self._auxiliary_evidence_cadence.resolve(tracking_result, None)

        detections = self.auxiliary_model.infer(frame)
        evidence_list = match_detections_to_tracks(
            tracking_result.tracks, detections, self.iou_threshold
        )
        fresh_evidence = {evidence.track_id: evidence for evidence in evidence_list}
        return self._auxiliary_evidence_cadence.resolve(tracking_result, fresh_evidence)
