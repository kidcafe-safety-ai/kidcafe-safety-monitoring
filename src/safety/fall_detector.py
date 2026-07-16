"""FALL_SUSPECT 상태머신 및 감지기.

계약: docs/interfaces.md FALL_SUSPECT·EventCause 계약
(상태 흐름 NORMAL → FALLING_CANDIDATE → FALL_CONFIRMED → COOLDOWN → NORMAL).

Track별로 독립된 상태머신을 유지하며, FALL_CONFIRMED 전이 시에만 Track당
1개의 FALL_SUSPECT Event를 생성한다. cause는 이번 PR에서 항상 None이다
(외부 접촉 원인 후보 추정은 후속 PR, ADR-016).

candidate 진입과 confirm은 서로 다른 시점의 근거를 사용한다 (CAUCAFall
Subject 1~6 개발 데이터로 튜닝하며 확인한 실제 낙상 패턴):
    - candidate 진입: 하강 속도 또는 높이 수축률 중 하나(동적 근거)만으로 충분하다.
      실제 낙상에서는 하강/수축이 먼저 나타나고(예: frame 68~71) 수평 자세는
      한참 뒤에야 도달하므로(예: frame 75+), 두 근거가 같은 프레임에 동시에
      있어야 한다는 조건은 실제 낙상을 거의 놓친다.
    - confirm: candidate 진입 이후 수평 자세(aspect_ratio 임계값 이상)가
      fall_confirm_sec 이상 지속돼야 한다. 동적 근거만으로는 앉기/무릎꿇기/
      줍기 같은 일상 동작과 구분되지 않으므로, 실제로 누운 자세까지 이어지는지
      확인하는 이 단계가 오탐을 억제한다.

알려진 한계 (Subject 1~6 Development 60개 실측 기준선, Recall 16.7%,
False alarm 0.0/분): aspect_ratio 기반 수평 자세 판정은 카메라 각도에 따라
일부 낙상 방향(특히 forward·left)을 놓친다 — 예: Subject 1 Fall forward는
영상 전체에서 aspect_ratio가 0.48을 넘지 않는다. bbox 기반 height/center_y
상대값으로 대체 경로를 추가하는 방안도 검증했으나, 같은 Development
데이터에서 무릎 꿇기·물건 줍기 등 일상 동작과 낙상의 height 압축량이
겹쳐(예: 물건 줍기 height 비율 0.52 vs 낙상 중앙값 0.517) 안전하게 분리되지
않아 폐기했다. 방향별 한계는 이어지는 pose keypoint 기반 보완으로 해소한다
(자세한 근거는 docs/fall_evaluation.md 참고).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from src.common.types import Event, Track, TrackingResult
from src.safety.fall_features import FallFeatureExtractor, FallFeatures
from src.safety.multi_track_history import MultiTrackHistory, TrackKey

_STATE_NORMAL = "NORMAL"
_STATE_FALLING_CANDIDATE = "FALLING_CANDIDATE"
_STATE_COOLDOWN = "COOLDOWN"


@dataclass
class FallDetectorConfig:
    """docs/interfaces.md FALL_SUSPECT 계약 기반 임계값. configs/fall_detection.json에서 로드한다."""

    history_window_sec: float = 2.0
    track_grace_sec: float = 0.5
    min_track_age_sec: float = 0.3
    fall_candidate_timeout_sec: float = 2.0
    fall_confirm_sec: float = 0.5
    cooldown_sec: float = 5.0

    horizontal_aspect_ratio_threshold: float = 1.3
    normal_aspect_ratio_threshold: float = 0.9
    fall_center_velocity_threshold: float = 1.5
    fall_foot_velocity_threshold: float = 1.2
    fall_height_shrink_rate_threshold: float = -1.0
    recovery_velocity_threshold: float = 0.3

    event_confidence_weights: Dict[str, float] = field(
        default_factory=lambda: {
            "posture": 0.35,
            "descent": 0.35,
            "duration": 0.2,
            "track_confidence": 0.1,
        }
    )

    def __post_init__(self) -> None:
        for name in (
            "track_grace_sec",
            "min_track_age_sec",
            "fall_candidate_timeout_sec",
            "fall_confirm_sec",
            "cooldown_sec",
            "recovery_velocity_threshold",
        ):
            if getattr(self, name) < 0:
                raise ValueError(f"{name}는 0 이상이어야 합니다.")
        if self.history_window_sec <= 0:
            raise ValueError("history_window_sec는 0보다 커야 합니다.")
        if self.fall_center_velocity_threshold <= 0 or self.fall_foot_velocity_threshold <= 0:
            raise ValueError(
                "fall_center_velocity_threshold/fall_foot_velocity_threshold는 0보다 커야 합니다."
            )
        if self.horizontal_aspect_ratio_threshold <= 0 or self.normal_aspect_ratio_threshold <= 0:
            raise ValueError("aspect_ratio 임계값은 0보다 커야 합니다.")
        if self.horizontal_aspect_ratio_threshold <= self.normal_aspect_ratio_threshold:
            raise ValueError(
                "horizontal_aspect_ratio_threshold는 normal_aspect_ratio_threshold보다 커야 합니다."
            )
        if any(weight < 0 for weight in self.event_confidence_weights.values()):
            raise ValueError("event_confidence_weights 값은 음수일 수 없습니다.")

    @classmethod
    def from_file(cls, path: str) -> "FallDetectorConfig":
        with open(path, "r", encoding="utf-8") as file:
            data = json.load(file)
        return cls(**data)


@dataclass
class _TrackState:
    state: str = _STATE_NORMAL
    candidate_since_sec: Optional[float] = None
    # 실제로 track이 관측된(process()가 호출된) 프레임에서만 누적되는 "누운 자세
    # 지속시간". Track 소실 중 흐른 시간은 포함하지 않는다 (아래 _visible_step_dt).
    horizontal_duration_sec: float = 0.0
    last_processed_sec: Optional[float] = None
    # candidate 진입 이후 관측된 하강 근거의 최댓값. 확정 시점에는 이미 정지해
    # 속도가 0에 가까우므로, confirm 순간의 특징이 아니라 이 값을 event_confidence에 사용한다.
    max_descent_score: float = 0.0
    cooldown_until_sec: Optional[float] = None


class FallDetector:
    """여러 Track의 상태를 독립적으로 관리하며 FALL_SUSPECT Event를 생성한다."""

    def __init__(self, fps: float, config: Optional[FallDetectorConfig] = None) -> None:
        if fps <= 0:
            raise ValueError("fps는 0보다 커야 합니다.")
        self.fps = fps
        self.config = config or FallDetectorConfig()
        self._history = MultiTrackHistory(
            fps=fps,
            history_window_sec=self.config.history_window_sec,
            track_grace_sec=self.config.track_grace_sec,
        )
        self._extractor = FallFeatureExtractor()
        self._states: Dict[TrackKey, _TrackState] = {}

    def process(self, tracking_result: TrackingResult) -> List[Event]:
        """한 프레임의 TrackingResult를 반영하고, FALL_CONFIRMED 전이가 있으면 Event를 반환한다."""
        self._history.update(tracking_result)
        now_sec = tracking_result.frame_number / self.fps
        video_source = tracking_result.video_source
        timestamp = tracking_result.timestamp

        events: List[Event] = []
        for track in tracking_result.tracks:
            key = (video_source, track.track_id)
            history = self._history.get_history(video_source, track.track_id)
            threshold = self.config.horizontal_aspect_ratio_threshold
            features = self._extractor.extract(history, threshold)
            if features is None:
                continue

            event = self._advance_state(
                key,
                features,
                now_sec,
                track,
                tracking_result.frame_number,
                video_source,
                timestamp,
            )
            if event is not None:
                events.append(event)

        self._forget_lost_tracks(video_source)
        return events

    def _forget_lost_tracks(self, video_source: str) -> None:
        """MultiTrackHistory가 grace period 초과로 잊은 Track의 상태도 함께 정리한다."""
        active_keys: Set[TrackKey] = set(self._history.active_keys())
        lost_keys = [
            key
            for key in list(self._states.keys())
            if key[0] == video_source and key not in active_keys
        ]
        for key in lost_keys:
            del self._states[key]

    def _visible_step_dt(self, state: _TrackState, now_sec: float) -> float:
        """이번 process() 호출과 이 Track이 마지막으로 관측된 시각 사이의 '유효' 경과 시간.

        Track이 grace period 동안 잠깐 소실됐다가 다시 나타나면 실제 경과 시간(raw_dt)에는
        관측되지 않은 구간이 섞여 있다. 정상적인 연속 프레임 간격(1/fps)보다 뚜렷하게 큰
        raw_dt는 소실 구간이 섞인 것으로 보고 0을 반환해 지속시간 누적에서 완전히
        제외한다. 일부만 인정(예: 최대 2/fps로 cap)하면 소실 시간의 일부가 여전히
        새어 들어가 실제보다 몇 프레임 이르게 confirm되므로, 부분 인정 대신
        전부-또는-전무 방식을 사용한다.
        """
        if state.last_processed_sec is None:
            return 0.0
        raw_dt = now_sec - state.last_processed_sec
        max_contiguous_step = (1.0 / self.fps) * 1.5
        return raw_dt if 0.0 < raw_dt <= max_contiguous_step else 0.0

    def _advance_state(
        self,
        key: TrackKey,
        features: FallFeatures,
        now_sec: float,
        track: Track,
        frame_number: int,
        video_source: str,
        timestamp: str,
    ) -> Optional[Event]:
        state = self._states.setdefault(key, _TrackState())

        if state.state == _STATE_NORMAL:
            self._try_enter_candidate(state, features, now_sec)
            return None

        if state.state == _STATE_FALLING_CANDIDATE:
            return self._advance_candidate(
                state, features, now_sec, track, frame_number, video_source, timestamp
            )

        if state.state == _STATE_COOLDOWN:
            self._advance_cooldown(state, features, now_sec)
            return None

        return None

    def _try_enter_candidate(
        self, state: _TrackState, features: FallFeatures, now_sec: float
    ) -> None:
        cfg = self.config
        if features.track_age_sec < cfg.min_track_age_sec:
            return
        if not self._dynamic_evidence(features):
            return
        state.state = _STATE_FALLING_CANDIDATE
        state.candidate_since_sec = now_sec
        state.horizontal_duration_sec = 0.0
        state.last_processed_sec = now_sec
        state.max_descent_score = self._descent_score(features)

    def _advance_candidate(
        self,
        state: _TrackState,
        features: FallFeatures,
        now_sec: float,
        track: Track,
        frame_number: int,
        video_source: str,
        timestamp: str,
    ) -> Optional[Event]:
        cfg = self.config
        step_dt = self._visible_step_dt(state, now_sec)
        state.last_processed_sec = now_sec

        if self._is_recovered(features):
            self._reset_to_normal(state)
            return None

        state.max_descent_score = max(state.max_descent_score, self._descent_score(features))

        if features.is_horizontal_posture:
            state.horizontal_duration_sec += step_dt
            if state.horizontal_duration_sec >= cfg.fall_confirm_sec:
                return self._confirm_fall(
                    state, features, now_sec, track, frame_number, video_source, timestamp
                )
        else:
            state.horizontal_duration_sec = 0.0

        if (
            state.candidate_since_sec is not None
            and now_sec - state.candidate_since_sec >= cfg.fall_candidate_timeout_sec
        ):
            # 누운 자세가 충분히 지속되지 못한 채 candidate 상태가 너무 길어지면
            # (예: 서 있지도 눕지도 않은 애매한 자세가 지속) NORMAL로 되돌린다.
            self._reset_to_normal(state)
        return None

    def _advance_cooldown(
        self, state: _TrackState, features: FallFeatures, now_sec: float
    ) -> None:
        # cooldown 만료 후에도 누워 있으면 재감지하지 않고, 회복 자세 확인 후 NORMAL로 전이한다.
        if now_sec >= (state.cooldown_until_sec or 0.0) and not features.is_horizontal_posture:
            state.state = _STATE_NORMAL
            state.cooldown_until_sec = None

    def _reset_to_normal(self, state: _TrackState) -> None:
        state.state = _STATE_NORMAL
        state.candidate_since_sec = None
        state.horizontal_duration_sec = 0.0
        state.last_processed_sec = None
        state.max_descent_score = 0.0

    def _confirm_fall(
        self,
        state: _TrackState,
        features: FallFeatures,
        now_sec: float,
        track: Track,
        frame_number: int,
        video_source: str,
        timestamp: str,
    ) -> Event:
        event_confidence = self._compute_event_confidence(features, state)

        state.state = _STATE_COOLDOWN
        state.cooldown_until_sec = now_sec + self.config.cooldown_sec
        state.candidate_since_sec = None
        state.horizontal_duration_sec = 0.0
        state.last_processed_sec = None
        state.max_descent_score = 0.0

        return Event.create(
            event_type="FALL_SUSPECT",
            track_id=track.track_id,
            zone_id="__global__",
            bbox=list(track.bbox),
            foot_point=list(track.foot_point),
            frame_number=frame_number,
            video_source=video_source,
            timestamp=timestamp,
            confidence=features.avg_confidence,
            event_confidence=event_confidence,
            cause=None,
        )

    def _dynamic_evidence(self, features: FallFeatures) -> bool:
        """candidate 진입 조건: 하강 속도 또는 높이 수축률 중 하나만 있어도 충분하다.

        수평 자세는 여기 포함하지 않는다 — 실제 낙상에서는 수평 자세가 하강/수축보다
        한참 뒤에 나타나므로(모듈 docstring 참고), 같은 프레임에 함께 요구하면
        candidate 진입 자체가 거의 발생하지 않는다. 수평 자세는 confirm 단계
        (_advance_candidate)에서 지속시간으로 별도 확인한다.
        """
        cfg = self.config
        descent = (
            features.center_vertical_velocity >= cfg.fall_center_velocity_threshold
            or features.foot_point_vertical_velocity >= cfg.fall_foot_velocity_threshold
        )
        height_shrink = features.height_change_rate <= cfg.fall_height_shrink_rate_threshold
        return descent or height_shrink

    def _descent_score(self, features: FallFeatures) -> float:
        cfg = self.config
        return min(
            1.0,
            max(
                features.center_vertical_velocity / cfg.fall_center_velocity_threshold,
                features.foot_point_vertical_velocity / cfg.fall_foot_velocity_threshold,
                0.0,
            ),
        )

    def _is_recovered(self, features: FallFeatures) -> bool:
        cfg = self.config
        return (
            features.aspect_ratio < cfg.normal_aspect_ratio_threshold
            and features.center_vertical_velocity <= cfg.recovery_velocity_threshold
        )

    def _compute_event_confidence(self, features: FallFeatures, state: _TrackState) -> float:
        cfg = self.config
        weights = cfg.event_confidence_weights

        posture_score = 1.0 if features.is_horizontal_posture else 0.0
        descent_score = state.max_descent_score
        if cfg.fall_confirm_sec > 0:
            duration_score = min(1.0, state.horizontal_duration_sec / cfg.fall_confirm_sec)
        else:
            duration_score = 1.0
        track_confidence_score = features.avg_confidence

        score = (
            weights.get("posture", 0.0) * posture_score
            + weights.get("descent", 0.0) * descent_score
            + weights.get("duration", 0.0) * duration_score
            + weights.get("track_confidence", 0.0) * track_confidence_score
        )
        return max(0.0, min(1.0, score))
