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
않아 폐기했다 (자세한 근거는 docs/fall_evaluation.md §5.2 참고).

Pose 보완(§5.3): PoseTracker(yolo26n-pose.pt)가 Track.keypoints를 채워주면,
confirm에 pose 기반 경로를 수평 자세 경로와 OR로 추가한다. keypoints가 없는
Track(기존 ByteTracker 사용 시)은 pose 경로가 항상 None을 반환해 자동으로
비활성화되므로 기존 bbox 전용 동작과 완전히 하위 호환된다.

pose 신호는 처음에 어깨-엉덩이 벡터 각도(torso_angle)를 시도했으나, 카메라를
향해/멀어지는 방향(깊이 방향)으로 쓰러지면 몸 전체가 2D 영상에 압축 투영되어
이 벡터도 수직에 가깝게 나온다 — bbox와 동일한 카메라 각도 문제가 골격
각도에도 나타난다. 대신 머리-엉덩이 상대 높이(src/safety/pose_features.py
PoseFeatures.head_hip_diff_norm)를 쓴다. 실측 결과 훨씬 안정적으로
분리된다(CAUCAFall Development: 낙상 지속 구간 최소 ~0.24 vs 일상 동작
최댓값 ~0.16).

recovery 판정은 pose가 "쓰러진 자세"로 보는 동안에는 회복으로 보지 않는다
— 그렇지 않으면 aspect_ratio가 낮게 유지되는 낙상(§5.1)에서 회복 조건이
만족돼 pose confirm 진행이 끊길 수 있다. 또한 회복 조건은 단일 프레임이
아니라 recovery_confirm_sec 이상 지속돼야 실제로 NORMAL로 되돌린다 — bbox
속도/자세가 프레임 하나에서 순간적으로 흔들려도(검출 jitter) candidate가
바로 초기화되지 않도록 하기 위함이다. pose 신호가 일시적으로 없는(keypoint
신뢰도 부족) 프레임에서는 pose_duration_sec을 0으로 초기화하지 않고 그대로
유지한다 — 잠깐의 keypoint 인식 실패로 이미 쌓인 지속시간이 사라지지 않게
하기 위함이며, candidate 전체가 무한정 유지되지는 않도록 fall_candidate_timeout_sec가
상한을 건다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from src.common.types import Event, Track, TrackingResult
from src.safety.fall_features import FallFeatureExtractor, FallFeatures
from src.safety.multi_track_history import MultiTrackHistory, TrackKey
from src.safety.pose_features import PoseFeatureExtractor, PoseFeatures

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

    # pose 기반 confirm 경로 (keypoints 없으면 자동 비활성화, 모듈 docstring 참고).
    # CAUCAFall Development 실측 기준(docs/fall_evaluation.md §5.3): 낙상 지속 구간
    # head_hip_diff_norm 최소 ~0.24, 일상 동작(물건 줍기 등) 최댓값 ~0.16.
    pose_fallen_threshold: float = 0.2
    pose_min_keypoint_conf: float = 0.3
    # 회복 조건이 이 시간 이상 지속돼야 실제로 candidate를 초기화한다 (단일 프레임
    # jitter로 candidate가 끊기지 않도록).
    recovery_confirm_sec: float = 0.3

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
            "recovery_confirm_sec",
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
        if not (-1 <= self.pose_fallen_threshold <= 1):
            raise ValueError("pose_fallen_threshold는 -1~1 사이여야 합니다.")
        if not (0 <= self.pose_min_keypoint_conf <= 1):
            raise ValueError("pose_min_keypoint_conf는 0~1 사이여야 합니다.")
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
    # pose 기반 confirm 경로의 지속시간. horizontal_duration_sec와 동일한 방식으로
    # 누적된다 (keypoints 없는 Track은 항상 0으로 유지되어 이 경로가 비활성화된다).
    # pose 신호가 일시적으로 없는 프레임에서는 0으로 초기화하지 않고 그대로 둔다
    # (모듈 docstring 참고).
    pose_duration_sec: float = 0.0
    # 회복 조건이 만족된 지속시간. recovery_confirm_sec 이상이어야 실제로 초기화한다.
    recovery_duration_sec: float = 0.0
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
        self._pose_extractor = PoseFeatureExtractor()
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

            pose_features = self._pose_extractor.extract(
                track,
                self.config.pose_fallen_threshold,
                self.config.pose_min_keypoint_conf,
            )

            event = self._advance_state(
                key,
                features,
                pose_features,
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
        pose_features: Optional[PoseFeatures],
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
                state,
                features,
                pose_features,
                now_sec,
                track,
                frame_number,
                video_source,
                timestamp,
            )

        if state.state == _STATE_COOLDOWN:
            self._advance_cooldown(state, features, pose_features, now_sec)
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
        state.pose_duration_sec = 0.0
        state.recovery_duration_sec = 0.0
        state.last_processed_sec = now_sec
        state.max_descent_score = self._descent_score(features)

    def _advance_candidate(
        self,
        state: _TrackState,
        features: FallFeatures,
        pose_features: Optional[PoseFeatures],
        now_sec: float,
        track: Track,
        frame_number: int,
        video_source: str,
        timestamp: str,
    ) -> Optional[Event]:
        cfg = self.config
        step_dt = self._visible_step_dt(state, now_sec)
        state.last_processed_sec = now_sec

        if self._is_recovered(features, pose_features):
            state.recovery_duration_sec += step_dt
            if state.recovery_duration_sec >= cfg.recovery_confirm_sec:
                self._reset_to_normal(state)
                return None
        else:
            state.recovery_duration_sec = 0.0

        state.max_descent_score = max(state.max_descent_score, self._descent_score(features))

        if features.is_horizontal_posture:
            state.horizontal_duration_sec += step_dt
        else:
            state.horizontal_duration_sec = 0.0

        if pose_features is not None:
            if pose_features.is_fallen_pose:
                state.pose_duration_sec += step_dt
            else:
                state.pose_duration_sec = 0.0
        # pose_features가 None(keypoint 신뢰도 부족 등)이면 pose_duration_sec을
        # 건드리지 않는다 — 짧은 인식 실패로 이미 쌓인 지속시간이 사라지지 않게
        # 하기 위함이다 (모듈 docstring 참고). candidate 전체는 fall_candidate_timeout_sec가
        # 상한을 건다.

        if (
            state.horizontal_duration_sec >= cfg.fall_confirm_sec
            or state.pose_duration_sec >= cfg.fall_confirm_sec
        ):
            return self._confirm_fall(
                state, features, now_sec, track, frame_number, video_source, timestamp
            )

        if (
            state.candidate_since_sec is not None
            and now_sec - state.candidate_since_sec >= cfg.fall_candidate_timeout_sec
        ):
            # 두 confirm 경로(수평 자세/pose) 모두 충분히 지속되지 못한 채 candidate
            # 상태가 너무 길어지면 (예: 서 있지도 눕지도 않은 애매한 자세가 지속)
            # NORMAL로 되돌린다.
            self._reset_to_normal(state)
        return None

    def _advance_cooldown(
        self,
        state: _TrackState,
        features: FallFeatures,
        pose_features: Optional[PoseFeatures],
        now_sec: float,
    ) -> None:
        # cooldown 만료 후에도 누워 있으면 재감지하지 않고, 회복 자세 확인 후 NORMAL로 전이한다.
        # bbox(is_horizontal_posture)만 보면 깊이 방향 낙상(§5.1)에서 pose는 여전히
        # 쓰러진 자세인데도 조기에 NORMAL로 전이해 같은 낙상을 다시 candidate로
        # 잡아 중복 Event를 만드는 문제가 있었다(S4_fall_forward 실측). recovery
        # 판정(_is_recovered)과 동일하게 pose가 쓰러진 자세로 보는 동안에는 회복으로
        # 보지 않는다.
        still_fallen = features.is_horizontal_posture or (
            pose_features is not None and pose_features.is_fallen_pose
        )
        if now_sec >= (state.cooldown_until_sec or 0.0) and not still_fallen:
            state.state = _STATE_NORMAL
            state.cooldown_until_sec = None

    def _reset_to_normal(self, state: _TrackState) -> None:
        state.state = _STATE_NORMAL
        state.candidate_since_sec = None
        state.horizontal_duration_sec = 0.0
        state.pose_duration_sec = 0.0
        state.recovery_duration_sec = 0.0
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
        state.pose_duration_sec = 0.0
        state.recovery_duration_sec = 0.0
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

    def _is_recovered(
        self, features: FallFeatures, pose_features: Optional[PoseFeatures]
    ) -> bool:
        # pose가 쓰러진 자세로 보는 동안에는 회복으로 보지 않는다. aspect_ratio가
        # 낮게 유지되는 낙상(모듈 docstring §5.1)에서 회복 조건이 자주 만족돼
        # pose confirm 진행이 중간에 끊기는 문제를 막기 위함이다.
        if pose_features is not None and pose_features.is_fallen_pose:
            return False
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
        # 두 confirm 경로(수평 자세/pose) 중 더 오래 지속된 쪽을 지속시간 점수로 쓴다.
        longest_duration = max(state.horizontal_duration_sec, state.pose_duration_sec)
        if cfg.fall_confirm_sec > 0:
            duration_score = min(1.0, longest_duration / cfg.fall_confirm_sec)
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
