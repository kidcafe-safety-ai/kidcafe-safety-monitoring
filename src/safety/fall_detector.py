"""Track별 ``FALL_SUSPECT`` 상태머신.

상태 흐름은 ``NORMAL -> FALLING_CANDIDATE -> COOLDOWN -> NORMAL``이다.
Candidate 진입은 bbox 동적 변화 또는 보조 모델 근거를 사용하고, 확정은
bbox 수평 자세, Pose, 보조 모델의 bounded temporal voting 중 하나로 한다.
회복은 지정된 시간 동안 지속되어야 하며, cooldown 중에는 같은 낙상을 다시
확정하지 않는다.

ReID가 없는 tracker의 ID 변경은 위치 기반 tombstone으로 보완한다.
``FALLING_CANDIDATE`` 상태는 Candidate Handoff로 진행 상황을 승계하고,
``COOLDOWN`` 상태는 cooldown inheritance와 Cooldown Handoff로 재확정을
억제한다. 승계 우선순위는 cooldown inheritance, Cooldown Handoff,
Candidate Handoff 순서다.

원인 후보 추정은 ``FallCauseAttributor``에 위임한다. 승계 전 Track ID는
victim alias로 전달해 lookback 이력을 유지한다. 세부 임계값과 평가 근거는
``docs/fall_evaluation.md``에 기록한다.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Dict, FrozenSet, List, Optional, Set

from src.common.types import Event, EventCause, Track, TrackingResult
from src.safety.fall_cause_attributor import FallCauseAttributor
from src.safety.fall_features import FallFeatureExtractor, FallFeatures
from src.safety.fall_model_matching import FallModelEvidence, compute_iou
from src.safety.multi_track_history import MultiTrackHistory, TrackKey
from src.safety.pose_features import PoseFeatureExtractor, PoseFeatures

LOGGER = logging.getLogger(__name__)

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
    # CAUCAFall Development 실측 기준(docs/fall_evaluation.md 참고): 낙상 지속 구간
    # head_hip_diff_norm 최소 ~0.24, 일상 동작(물건 줍기 등) 최댓값 ~0.16.
    pose_fallen_threshold: float = 0.2
    pose_min_keypoint_conf: float = 0.3
    # 회복 조건이 이 시간 이상 지속돼야 실제로 candidate를 초기화한다 (단일 프레임
    # jitter로 candidate가 끊기지 않도록).
    recovery_confirm_sec: float = 0.3

    # fine-tuned fall/nofall 모델 기반 confirm 경로 (bounded temporal voting,
    # 모듈 docstring 참고). model_evidence를 process()에 전달하지 않으면
    # 완전히 비활성화된다. model_confirm_sec: 최근 model_vote_window_sec
    # 구간 안에서 label="fall"로 관측된 시간의 합이 이 값 이상이면 confirm된다.
    model_confirm_sec: float = 0.2
    # temporal voting의 슬라이딩 윈도우 크기. model_confirm_sec보다 작으면
    # 정의상 confirm에 절대 도달할 수 없으므로 __post_init__에서 검증한다.
    model_vote_window_sec: float = 0.5
    # model 기반 candidate 진입 임계값 (모듈 docstring 참고) — ReID 없이
    # 재획득된 Track이 이미 쓰러진 상태라 bbox 동적 근거가 없을 때도, 윈도우
    # 내 누적 fall 시간이 이 값 이상이면 candidate에 진입한다.
    # model_confirm_sec보다 반드시 작아야 한다(단일 프레임으로 진입과 동시에
    # confirm되는 것을 막기 위해 __post_init__에서 검증).
    model_candidate_entry_sec: float = 0.1
    # 공간 기반 cooldown 승계(모듈 docstring)의 최소 IoU. confirm된 Track의
    # bbox와 새로 생성된 Track의 bbox가 이 값 이상 겹치면 같은 사람의
    # 재검출로 보고 남은 cooldown을 물려준다.
    cooldown_inherit_iou_threshold: float = 0.3

    # Candidate Handoff는 candidate 중 ID가 바뀌어도 진행 시간을 보존한다.
    # Tombstone은 TTL과 candidate timeout 중 먼저 도달하는 시점에 만료한다.
    candidate_handoff_ttl_sec: float = 1.0
    candidate_handoff_iou_threshold: float = 0.3
    # IoU와 정규화된 foot_point 거리 조건을 모두 만족해야 한다.
    candidate_handoff_max_foot_distance_norm: float = 0.5

    # Cooldown Handoff는 소실 직전 위치를 사용해 재검출된 Track에 cooldown을
    # 승계한다. 만료 시각은 기존 cooldown과 마지막 관측 기준 TTL 중 늦은 값이다.
    cooldown_handoff_ttl_sec: float = 3.5
    # 더 긴 재획득 간격을 허용하므로 짧은 cooldown inheritance보다 낮게 둔다.
    cooldown_handoff_iou_threshold: float = 0.2
    cooldown_handoff_max_foot_distance_norm: float = 0.5

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
            "cooldown_sec",
            "recovery_velocity_threshold",
            "recovery_confirm_sec",
        ):
            if getattr(self, name) < 0:
                raise ValueError(f"{name}는 0 이상이어야 합니다.")
        for name in (
            "fall_confirm_sec",
            "model_confirm_sec",
            "model_vote_window_sec",
            "model_candidate_entry_sec",
        ):
            # 0을 허용하면 candidate 진입 직후 지속시간 누적이 전혀 없어도
            # "0.0 >= 0.0"이 참이 되어 즉시 confirm된다 (증거 없이 확정하는
            # 결함). 네 값 모두 반드시 0보다 커야 한다.
            if getattr(self, name) <= 0:
                raise ValueError(f"{name}는 0보다 커야 합니다.")
        if self.model_vote_window_sec < self.model_confirm_sec:
            raise ValueError(
                "model_vote_window_sec는 model_confirm_sec 이상이어야 합니다 "
                "(윈도우가 더 작으면 confirm에 정의상 도달할 수 없습니다)."
            )
        if self.model_candidate_entry_sec >= self.model_confirm_sec:
            raise ValueError(
                "model_candidate_entry_sec는 model_confirm_sec보다 작아야 합니다 "
                "(같은 프레임에 candidate 진입과 confirm이 동시에 발생하지 않도록)."
            )
        if not (0.0 < self.cooldown_inherit_iou_threshold <= 1.0):
            raise ValueError("cooldown_inherit_iou_threshold는 0보다 크고 1 이하여야 합니다.")
        if self.candidate_handoff_ttl_sec <= 0:
            raise ValueError("candidate_handoff_ttl_sec는 0보다 커야 합니다.")
        if not (0.0 < self.candidate_handoff_iou_threshold <= 1.0):
            raise ValueError("candidate_handoff_iou_threshold는 0보다 크고 1 이하여야 합니다.")
        if self.candidate_handoff_max_foot_distance_norm <= 0:
            raise ValueError("candidate_handoff_max_foot_distance_norm는 0보다 커야 합니다.")
        if self.cooldown_handoff_ttl_sec <= 0:
            raise ValueError("cooldown_handoff_ttl_sec는 0보다 커야 합니다.")
        if not (0.0 < self.cooldown_handoff_iou_threshold <= 1.0):
            raise ValueError("cooldown_handoff_iou_threshold는 0보다 크고 1 이하여야 합니다.")
        if self.cooldown_handoff_max_foot_distance_norm <= 0:
            raise ValueError("cooldown_handoff_max_foot_distance_norm는 0보다 커야 합니다.")
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
        # "cause_attribution"은 FallCauseAttributorConfig 전용 하위 섹션이다 —
        # FallDetectorConfig는 이 키를 모르므로(**data 언패킹이 TypeError를 냄)
        # 여기서 제거한다. 같은 JSON 파일을 공유하되 두 config는 서로 독립이다
        # (src/safety/fall_cause_attributor.py 모듈 docstring 참고).
        data = {key: value for key, value in data.items() if key != "cause_attribution"}
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
    # fine-tuned 모델 기반 confirm 경로: 최근 model_vote_window_sec 구간 안에서
    # label="fall"이었던 (timestamp, step_dt) 목록. model_duration_sec은 이
    # 목록의 step_dt 합이다 (모듈 docstring, _accumulate_model_duration 참고).
    model_fall_evidence: List[tuple] = field(default_factory=list)
    model_duration_sec: float = 0.0
    last_processed_sec: Optional[float] = None
    # candidate 진입 이후 관측된 하강 근거의 최댓값. 확정 시점에는 이미 정지해
    # 속도가 0에 가까우므로, confirm 순간의 특징이 아니라 이 값을 event_confidence에 사용한다.
    max_descent_score: float = 0.0
    cooldown_until_sec: Optional[float] = None
    # 오프라인 평가 진단용이며 Event schema에는 포함하지 않는다.
    candidate_entry_reason: Optional[str] = None
    # Handoff tombstone을 즉시 만들 수 있도록 마지막 관측 위치를 보존한다.
    last_bbox: Optional[List[float]] = None
    last_foot_point: Optional[List[float]] = None
    last_seen_sec: Optional[float] = None
    # 이 candidate가 (다단 포함) 승계받아온 모든 원본 track_id. 한 번도
    # 승계받지 않았으면 빈 집합 — Event.track_id는 항상 현재 track_id를
    # 쓰고, 이 값은 cause attribution의 victim alias 집합에만 사용한다.
    origin_track_ids: FrozenSet[int] = field(default_factory=frozenset)


@dataclass(frozen=True)
class _CooldownTombstone:
    """confirm된 Track이 남기는 흔적 — 공간 기반 cooldown 승계에 쓴다 (모듈 docstring)."""

    bbox: List[float]
    cooldown_until_sec: float


@dataclass(frozen=True)
class _CandidateTombstone:
    """FALLING_CANDIDATE 상태에서 사라진 Track이 남기는 흔적 (Candidate Handoff,

    모듈 docstring 참고). cooldown_inherit과 달리 confirm 전 진행 상황
    (candidate_since_sec, max_descent_score)을 물려준다 — horizontal/pose/
    model duration은 승계하지 않는다(새 Track에서 정적 근거를 다시 쌓아야
    즉시 확정을 막을 수 있다).
    """

    # 이 tombstone을 만든 바로 그 소실 시점의 track_id. alias 체인 중 이
    # id만 자신의 _TrackState가 아직 self._states에 살아있다(다른 alias는
    # 이미 이전 승계 때 지워졌다) — 재등장 취소는 이 id에 대해서만 성립한다
    # (아래 origin_track_ids 필드 설명 참고).
    source_track_id: int
    # alias 체인 전체(source_track_id 포함). 승계 시 새 Track의
    # origin_track_ids를 만들 때(자기 자신 제외)와, 지워야 할 옛 _TrackState
    # 목록을 정할 때(승계받은 현재 Track 제외) 모두 이 값을 쓴다.
    origin_track_ids: FrozenSet[int]
    bbox: List[float]
    foot_point: List[float]
    candidate_since_sec: float
    max_descent_score: float
    last_seen_sec: float
    expires_at_sec: float


@dataclass(frozen=True)
class _CooldownHandoffTombstone:
    """COOLDOWN 상태에서 사라진 Track이 남기는 흔적 (Cooldown Handoff,

    FallDetectorConfig.cooldown_handoff_ttl_sec 주석 참고). 기존
    _CooldownTombstone(confirm 시점 등록, cooldown_until_sec 기준 만료)과
    별개다 — 이건 소실 시점(last_seen_sec) 기준 TTL로 만료돼, cooldown이
    이미 지났어도 최근 소실이면 여전히 승계할 수 있다. _CandidateTombstone과
    동일한 source_track_id/origin_track_ids 패턴을 그대로 쓴다.
    """

    source_track_id: int
    origin_track_ids: FrozenSet[int]
    bbox: List[float]
    foot_point: List[float]
    # cooldown_until_sec은 그대로 물려준다 — 이미 지난 값이어도 상관없다.
    # _advance_cooldown()이 그 값과 now_sec을 비교해 still_fallen이면 계속
    # COOLDOWN을 유지하고, 아니면 그 자리에서 바로 회복 판정을 한다(실제
    # 근거 기반 재확인이지, tombstone이 회복을 보장하지는 않는다).
    cooldown_until_sec: float
    last_seen_sec: float
    expires_at_sec: float


def _euclidean(a: List[float], b: List[float]) -> float:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


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
        # video_source -> 최근 confirm된 Track들의 흔적 (공간 기반 cooldown 승계,
        # 모듈 docstring 참고).
        self._cooldown_tombstones: Dict[str, List[_CooldownTombstone]] = {}
        # video_source -> 소실된 FALLING_CANDIDATE Track들의 흔적 (Candidate
        # Handoff, 모듈 docstring 참고).
        self._candidate_tombstones: Dict[str, List[_CandidateTombstone]] = {}
        # video_source -> 소실된 COOLDOWN Track들의 흔적 (Cooldown Handoff,
        # FallDetectorConfig.cooldown_handoff_ttl_sec 주석 참고).
        self._cooldown_handoff_tombstones: Dict[str, List[_CooldownHandoffTombstone]] = {}

    def process(
        self,
        tracking_result: TrackingResult,
        model_evidence: Optional[Dict[int, FallModelEvidence]] = None,
        cause_attributor: Optional[FallCauseAttributor] = None,
        diagnostics: Optional[List[dict]] = None,
    ) -> List[Event]:
        """한 프레임의 TrackingResult를 반영하고, FALL_CONFIRMED 전이가 있으면 Event를 반환한다.

        model_evidence: track_id -> FallModelEvidence. fine-tuned fall/nofall 모델을
            쓰지 않으면(호출자가 AuxiliaryFallModel을 아예 안 쓰거나 enabled=False)
            None으로 두면 된다 — model confirm 경로가 완전히 비활성화되어 기존
            bbox/pose 전용 동작과 하위 호환된다. 이 딕셔너리를 만드는 IoU 매칭은
            이 클래스의 책임이 아니다 (src/safety/fall_model_matching.py).
        cause_attributor: 지정하면 confirm 시 FallCauseAttributor.attribute()를
            호출해 EventCause를 채운다. None이면(기본값, 기존 호출과 하위 호환)
            cause는 항상 None이다.
        diagnostics: 지정하면 confirm이 발생할 때마다 candidate 진입 이유
            (dynamic/model/handoff)와 confirm 경로(bbox/pose/model)를 담은 dict를
            append한다.
            Event dataclass 자체는 건드리지 않는다 — evaluate_fall.py 같은
            오프라인 분석 전용 side-channel이다. None이면(기본값) 완전히
            비활성화되어 기존 호출과 하위 호환된다.
        """
        self._history.update(tracking_result)
        now_sec = tracking_result.frame_number / self.fps
        video_source = tracking_result.video_source
        timestamp = tracking_result.timestamp

        # 이번 프레임에 실제로 관측된 track_id 집합. Candidate Handoff는 이
        # 값을 메인 루프보다 먼저 확정해서 처리해야 한다 — "Track이 처음
        # 비활성화된 프레임"에 바로 tombstone을 남겨야 같은 프레임에 나타난
        # 새 Track이 즉시 승계할 수 있다(모듈 docstring). MultiTrackHistory의
        # grace period 기반 _forget_lost_tracks()는 이 시점엔 아직 그 Track을
        # active로 취급하므로 너무 늦다.
        current_active_ids = {track.track_id for track in tracking_result.tracks}
        self._update_candidate_tombstones(video_source, current_active_ids, now_sec)
        self._update_cooldown_handoff_tombstones(video_source, current_active_ids, now_sec)

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
            evidence = self._resolve_model_evidence(model_evidence, track.track_id)

            event = self._advance_state(
                key,
                features,
                pose_features,
                evidence,
                now_sec,
                track,
                tracking_result.frame_number,
                video_source,
                timestamp,
                cause_attributor,
                diagnostics,
            )
            if event is not None:
                events.append(event)

        self._forget_lost_tracks(video_source, now_sec)
        self._prune_expired_tombstones(video_source, now_sec)
        return events

    @staticmethod
    def _resolve_model_evidence(
        model_evidence: Optional[Dict[int, FallModelEvidence]], track_id: int
    ) -> Optional[FallModelEvidence]:
        """model_evidence 딕셔너리 자체가 None이면 모델 경로를 완전히 비활성화한다

        (기존 호출과 하위 호환). 딕셔너리는 전달됐지만 이 track_id가 빠져 있으면
        "모델을 안 쓴다"가 아니라 "이번 프레임에 이 Track을 모델이 못 봤다"는
        뜻이므로 label="unknown"으로 취급한다 — "fall"로 잘못 채워 넣어
        근거를 조작하지 않으면서도, 이 프레임이 윈도우 근거 목록에서
        조용히 통째로 빠지는 것과는 다른 의미임을 남긴다 (호출자가 매 프레임
        모든 Track을 evidence 딕셔너리에 넣는 것에 의존하지 않아도 안전하다).

        딕셔너리의 key(track_id)와 값의 FallModelEvidence.track_id가 다르면
        조용히 그대로 쓰지 않고 즉시 오류를 낸다 — 잘못 연결된 evidence가
        엉뚱한 Track을 낙상으로 확정시키는 것이 가장 위험한 실패 모드이기
        때문이다.
        """
        if model_evidence is None:
            return None
        unknown = FallModelEvidence(
            track_id=track_id, label="unknown", confidence=None, iou=None
        )
        evidence = model_evidence.get(track_id, unknown)
        if evidence.track_id != track_id:
            raise ValueError(
                f"model_evidence[{track_id}].track_id가 {evidence.track_id}로 "
                "다릅니다 — key와 FallModelEvidence.track_id는 항상 일치해야 합니다."
            )
        return evidence

    def _forget_lost_tracks(self, video_source: str, now_sec: float) -> None:
        """MultiTrackHistory가 grace period 초과로 잊은 Track의 상태도 함께 정리한다.

        COOLDOWN 상태는 예외로 지우지 않는다(모듈 docstring, S4_fall_forward
        중복 Event 근본 원인, docs/fall_evaluation.md 참고) — 이미 확정된
        낙상은 track_grace_sec을 넘는
        길이로 잠깐 소실돼도(누운 자세는 occlusion이 흔함) cooldown 기억이
        살아있어야 재검출 시 같은 낙상을 다시 candidate로 잡지 않는다.

        다만 cooldown_until_sec이 이미 지난 COOLDOWN 상태까지 무기한 보존하면
        실시간 스트림에서 Track이 다시 나타나지 않는 한(카메라 밖으로 나감 등)
        상태가 낙상마다 하나씩 영구히 쌓인다 — 이 상태는 다시 관측되지 않는 한
        재검출 억제 목적으로 더는 쓰이지 않으므로, cooldown 만료 이후에는
        소실된 Track과 함께 지워도 안전하다.
        """
        active_keys: Set[TrackKey] = set(self._history.active_keys())
        lost_keys = [
            key
            for key in list(self._states.keys())
            if key[0] == video_source
            and key not in active_keys
            and (
                self._states[key].state != _STATE_COOLDOWN
                or (
                    self._states[key].cooldown_until_sec is not None
                    and self._states[key].cooldown_until_sec <= now_sec
                )
            )
        ]
        for key in lost_keys:
            del self._states[key]

    def _prune_expired_tombstones(self, video_source: str, now_sec: float) -> None:
        tombstones = self._cooldown_tombstones.get(video_source)
        if not tombstones:
            return
        remaining = [t for t in tombstones if t.cooldown_until_sec > now_sec]
        if remaining:
            self._cooldown_tombstones[video_source] = remaining
        else:
            del self._cooldown_tombstones[video_source]

    def _try_inherit_cooldown(
        self, state: _TrackState, track: Track, video_source: str, now_sec: float
    ) -> None:
        """새로 생성된 _TrackState가 최근 confirm된(같은 video_source) Track과

        공간적으로 겹치면, NORMAL 대신 그 남은 cooldown을 물려받는다 (모듈
        docstring — ReID 없이 재획득된 같은 사람이 곧바로 새 candidate/confirm을
        만드는 것을 막기 위함). 같은 낙상이 짧은 시간에 여러 Track ID로
        재획득될 수 있으므로 tombstone은 첫 승계 때 소비하지 않고 cooldown
        만료까지 유지한다.
        """
        self._prune_expired_tombstones(video_source, now_sec)
        tombstones = self._cooldown_tombstones.get(video_source)
        if not tombstones:
            return

        threshold = self.config.cooldown_inherit_iou_threshold
        for tombstone in tombstones:
            if compute_iou(track.bbox, tombstone.bbox) >= threshold:
                state.state = _STATE_COOLDOWN
                state.cooldown_until_sec = tombstone.cooldown_until_sec
                return

    def _update_cooldown_handoff_tombstones(
        self, video_source: str, current_active_ids: Set[int], now_sec: float
    ) -> None:
        """재등장·만료·신규 소실 순서로 cooldown tombstone을 갱신한다.

        source Track의 상태가 남아 있으면 tombstone을 취소한다. 상태가 이미
        정리됐다면 같은 ID가 재등장해도 handoff로 복원할 수 있도록 유지한다.
        """
        tombstones = self._cooldown_handoff_tombstones.get(video_source, [])

        reappeared_source_ids = {
            t.source_track_id
            for t in tombstones
            if t.source_track_id in current_active_ids
            and (video_source, t.source_track_id) in self._states
        }
        if reappeared_source_ids:
            tombstones = [
                t for t in tombstones if t.source_track_id not in reappeared_source_ids
            ]

        tombstones = [t for t in tombstones if t.expires_at_sec > now_sec]

        already_tombstoned_ids = {
            track_id for t in tombstones for track_id in t.origin_track_ids
        }
        for key, state in self._states.items():
            if key[0] != video_source or key[1] in current_active_ids:
                continue
            if state.state != _STATE_COOLDOWN:
                continue
            if key[1] in already_tombstoned_ids:
                continue
            new_tombstone = self._build_cooldown_handoff_tombstone(key[1], state, now_sec)
            if new_tombstone is not None:
                tombstones.append(new_tombstone)

        if tombstones:
            self._cooldown_handoff_tombstones[video_source] = tombstones
        else:
            self._cooldown_handoff_tombstones.pop(video_source, None)

    def _build_cooldown_handoff_tombstone(
        self, track_id: int, state: _TrackState, now_sec: float
    ) -> Optional[_CooldownHandoffTombstone]:
        """방금 비활성화된 COOLDOWN 상태에서 tombstone을 만든다.

        _build_candidate_tombstone과 동일하게 last_bbox/last_foot_point/
        last_seen_sec/cooldown_until_sec 중 하나라도 없으면(방어적으로)
        tombstone을 만들지 않는다.
        """
        if (
            state.last_bbox is None
            or state.last_foot_point is None
            or state.last_seen_sec is None
            or state.cooldown_until_sec is None
        ):
            return None

        # 원래 cooldown이 남아 있는 동안 tombstone이 먼저 만료되지 않게 한다.
        expires_at_sec = max(
            state.cooldown_until_sec,
            state.last_seen_sec + self.config.cooldown_handoff_ttl_sec,
        )
        if expires_at_sec <= now_sec:
            return None

        return _CooldownHandoffTombstone(
            source_track_id=track_id,
            origin_track_ids=state.origin_track_ids | {track_id},
            bbox=list(state.last_bbox),
            foot_point=list(state.last_foot_point),
            cooldown_until_sec=state.cooldown_until_sec,
            last_seen_sec=state.last_seen_sec,
            expires_at_sec=expires_at_sec,
        )

    def _try_cooldown_handoff(
        self, state: _TrackState, track: Track, video_source: str, now_sec: float
    ) -> bool:
        """_try_inherit_cooldown이 실패했을 때만 호출한다(기존 짧은 재획득

        경로가 여전히 우선). IoU와 정규화된 foot_point 거리를 candidate_handoff와
        동일하게 AND로 결합한다(cooldown_handoff_iou_threshold 주석 —
        시행착오로 OR을 시도했다가 서 있는 다른 Track까지 foot 거리만으로
        잘못 승계되는 오탐이 재현돼 AND로 되돌렸다). IoU가 가장 큰 tombstone을
        고른다.
        """
        tombstones = self._cooldown_handoff_tombstones.get(video_source)
        if not tombstones:
            return False

        iou_threshold = self.config.cooldown_handoff_iou_threshold
        max_foot_distance = self.config.cooldown_handoff_max_foot_distance_norm
        track_height = track.bbox[3] - track.bbox[1]

        best_tombstone: Optional[_CooldownHandoffTombstone] = None
        best_iou = -1.0
        for tombstone in tombstones:
            iou = compute_iou(track.bbox, tombstone.bbox)
            if iou < iou_threshold:
                continue
            foot_distance_norm = _euclidean(track.foot_point, tombstone.foot_point) / (
                track_height if track_height > 0 else 1.0
            )
            if foot_distance_norm > max_foot_distance:
                continue
            if iou > best_iou:
                best_tombstone = tombstone
                best_iou = iou

        if best_tombstone is None:
            return False

        state.state = _STATE_COOLDOWN
        state.cooldown_until_sec = best_tombstone.cooldown_until_sec
        state.origin_track_ids = best_tombstone.origin_track_ids - {track.track_id}

        remaining = [t for t in tombstones if t is not best_tombstone]
        if remaining:
            self._cooldown_handoff_tombstones[video_source] = remaining
        else:
            self._cooldown_handoff_tombstones.pop(video_source, None)

        for origin_id in best_tombstone.origin_track_ids:
            if origin_id == track.track_id:
                continue
            self._states.pop((video_source, origin_id), None)
        return True

    def _update_candidate_tombstones(
        self, video_source: str, current_active_ids: Set[int], now_sec: float
    ) -> None:
        """재등장·만료·신규 소실 순서로 candidate tombstone을 갱신한다.

        source Track의 상태가 남아 있을 때만 재등장으로 취소한다. 이미 정리된
        source 또는 과거 alias는 정상 handoff 대상으로 유지한다.
        """
        tombstones = self._candidate_tombstones.get(video_source, [])

        reappeared_source_ids = {
            tombstone.source_track_id
            for tombstone in tombstones
            if tombstone.source_track_id in current_active_ids
            and (video_source, tombstone.source_track_id) in self._states
        }
        if reappeared_source_ids:
            tombstones = [
                t for t in tombstones if t.source_track_id not in reappeared_source_ids
            ]

        tombstones = [t for t in tombstones if t.expires_at_sec > now_sec]

        already_tombstoned_ids = {
            track_id for tombstone in tombstones for track_id in tombstone.origin_track_ids
        }
        for key, state in self._states.items():
            if key[0] != video_source or key[1] in current_active_ids:
                continue
            if state.state != _STATE_FALLING_CANDIDATE:
                continue
            if key[1] in already_tombstoned_ids:
                continue
            new_tombstone = self._build_candidate_tombstone(key[1], state, now_sec)
            if new_tombstone is not None:
                tombstones.append(new_tombstone)

        if tombstones:
            self._candidate_tombstones[video_source] = tombstones
        else:
            self._candidate_tombstones.pop(video_source, None)

    def _build_candidate_tombstone(
        self, track_id: int, state: _TrackState, now_sec: float
    ) -> Optional[_CandidateTombstone]:
        """방금 비활성화된 FALLING_CANDIDATE 상태에서 tombstone을 만든다.

        last_bbox/last_foot_point/last_seen_sec/candidate_since_sec 중 하나라도
        없으면(이론상 FALLING_CANDIDATE는 최소 한 번은 관측돼야 도달하므로
        발생하지 않아야 하지만, 방어적으로) tombstone을 만들지 않는다 —
        불완전한 tombstone으로 엉뚱한 매칭을 만드는 것보다 승계를 포기하는
        편이 안전하다.
        """
        if (
            state.last_bbox is None
            or state.last_foot_point is None
            or state.last_seen_sec is None
            or state.candidate_since_sec is None
        ):
            return None

        cfg = self.config
        # TTL과 candidate timeout 중 먼저 도달하는 시점에 만료한다 — candidate
        # 전체 상한(fall_candidate_timeout_sec)을 넘겨서까지 승계를 허용하면
        # 이미 타임아웃됐어야 할 candidate가 다른 Track에서 부활하는 셈이다.
        ttl_expiry = state.last_seen_sec + cfg.candidate_handoff_ttl_sec
        candidate_expiry = state.candidate_since_sec + cfg.fall_candidate_timeout_sec
        expires_at_sec = min(ttl_expiry, candidate_expiry)
        if expires_at_sec <= now_sec:
            return None

        return _CandidateTombstone(
            source_track_id=track_id,
            origin_track_ids=state.origin_track_ids | {track_id},
            bbox=list(state.last_bbox),
            foot_point=list(state.last_foot_point),
            candidate_since_sec=state.candidate_since_sec,
            max_descent_score=state.max_descent_score,
            last_seen_sec=state.last_seen_sec,
            expires_at_sec=expires_at_sec,
        )

    def _try_candidate_handoff(
        self, state: _TrackState, track: Track, video_source: str, now_sec: float
    ) -> bool:
        """새로 생성된 _TrackState가 최근 소실된 FALLING_CANDIDATE Track과

        공간적으로 겹치면, NORMAL 대신 그 candidate 진행 상황(candidate_since_sec,
        max_descent_score)을 물려받는다(모듈 docstring). 호출자(`_advance_state`)가
        `_try_inherit_cooldown`을 먼저 시도해 실패했을 때만 불러야 한다 —
        cooldown 승계가 candidate 승계보다 항상 우선한다.

        horizontal/pose/model duration은 의도적으로 승계하지 않는다 — 새
        Track에서 정적 근거를 처음부터 다시 쌓아야, 근거 없이 즉시
        confirm되는 것을 막을 수 있다(모듈 docstring).
        """
        tombstones = self._candidate_tombstones.get(video_source)
        if not tombstones:
            return False

        iou_threshold = self.config.candidate_handoff_iou_threshold
        max_foot_distance = self.config.candidate_handoff_max_foot_distance_norm
        track_height = track.bbox[3] - track.bbox[1]

        best_tombstone: Optional[_CandidateTombstone] = None
        best_iou = -1.0
        for tombstone in tombstones:
            iou = compute_iou(track.bbox, tombstone.bbox)
            if iou < iou_threshold:
                continue
            foot_distance_norm = _euclidean(track.foot_point, tombstone.foot_point) / (
                track_height if track_height > 0 else 1.0
            )
            if foot_distance_norm > max_foot_distance:
                continue
            if iou > best_iou:
                best_tombstone = tombstone
                best_iou = iou

        if best_tombstone is None:
            return False

        # alias가 이전 ID로 돌아와도 현재 Track 자신은 origin에서 제외한다.
        state.state = _STATE_FALLING_CANDIDATE
        state.candidate_since_sec = best_tombstone.candidate_since_sec
        state.max_descent_score = best_tombstone.max_descent_score
        state.origin_track_ids = best_tombstone.origin_track_ids - {track.track_id}
        state.candidate_entry_reason = "handoff"

        # Tombstone 하나는 한 Track만 소비할 수 있다.
        remaining = [t for t in tombstones if t is not best_tombstone]
        if remaining:
            self._candidate_tombstones[video_source] = remaining
        else:
            self._candidate_tombstones.pop(video_source, None)

        # 소비된 tombstone이 다시 생성되지 않도록 원본 상태를 정리한다.
        # 현재 Track은 alias 복귀일 수 있으므로 삭제 대상에서 제외한다.
        for origin_id in best_tombstone.origin_track_ids:
            if origin_id == track.track_id:
                continue
            self._states.pop((video_source, origin_id), None)
        return True

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
        model_evidence: Optional[FallModelEvidence],
        now_sec: float,
        track: Track,
        frame_number: int,
        video_source: str,
        timestamp: str,
        cause_attributor: Optional[FallCauseAttributor],
        diagnostics: Optional[List[dict]] = None,
    ) -> Optional[Event]:
        is_new_track = key not in self._states
        state = self._states.setdefault(key, _TrackState())
        if is_new_track:
            # 공간 기반 cooldown 승계(모듈 docstring) — ReID 없이 재획득된
            # 같은 사람이 곧바로 새 candidate/confirm을 만들지 않도록, 이
            # video_source의 최근 confirm 위치와 겹치는지 먼저 확인한다.
            self._try_inherit_cooldown(state, track, video_source, now_sec)
            if state.state == _STATE_NORMAL:
                # 기존 cooldown 승계가 실패했을 때만 Cooldown Handoff를
                # 시도한다(FallDetectorConfig.cooldown_handoff_ttl_sec 주석
                # 참고) — 짧은 재획득은 기존 경로가 그대로 처리하고, 이건
                # 그 경로가 놓치는 두 경우(소실 중 cooldown 만료, IoU 미달
                # 대신 foot 거리로 매칭)만 추가로 덮는다.
                self._try_cooldown_handoff(state, track, video_source, now_sec)
            if state.state == _STATE_NORMAL:
                # 이미 확정된 낙상의 cooldown 승계가 candidate 승계보다 우선한다.
                self._try_candidate_handoff(state, track, video_source, now_sec)

        # step_dt 계산과 모델 근거 갱신은 상태와 무관하게 매 프레임 한 번만
        # 수행한다(모듈 docstring, model 기반 candidate 진입 참고) — NORMAL
        # 상태에서도 근거가 쌓여야 model-assisted 진입 판정을 할 수 있다.
        # last_processed_sec을 여기서 먼저 읽어 step_dt를 구한 뒤에 갱신해야
        # 하므로, 각 분기 함수는 더 이상 스스로 step_dt를 계산하거나
        # last_processed_sec을 건드리지 않는다.
        step_dt = self._visible_step_dt(state, now_sec)
        self._accumulate_model_duration(state, model_evidence, step_dt, now_sec)
        state.last_processed_sec = now_sec
        # Candidate Handoff(모듈 docstring)용 — 이 Track이 사라지는 바로 그
        # 순간의 위치를 알아야 다음 프레임에 바로 tombstone을 만들 수 있다.
        state.last_bbox = list(track.bbox)
        state.last_foot_point = list(track.foot_point)
        state.last_seen_sec = now_sec

        if state.state == _STATE_NORMAL:
            self._try_enter_candidate(state, features, now_sec)
            return None

        if state.state == _STATE_FALLING_CANDIDATE:
            return self._advance_candidate(
                state,
                features,
                pose_features,
                step_dt,
                now_sec,
                track,
                frame_number,
                video_source,
                timestamp,
                cause_attributor,
                diagnostics,
            )

        if state.state == _STATE_COOLDOWN:
            self._advance_cooldown(
                state, features, pose_features, model_evidence, step_dt, now_sec
            )
            return None

        return None

    def _try_enter_candidate(
        self, state: _TrackState, features: FallFeatures, now_sec: float
    ) -> None:
        cfg = self.config
        if features.track_age_sec < cfg.min_track_age_sec:
            return
        # bbox 동적 근거(기존 경로) OR model 기반 근거(모듈 docstring, ReID
        # 없이 재획득된 "이미 쓰러진" 새 Track 대응) 중 하나만 있어도 진입한다.
        is_dynamic = self._dynamic_evidence(features)
        if not is_dynamic and not self._model_candidate_ready(state):
            return
        state.state = _STATE_FALLING_CANDIDATE
        state.candidate_since_sec = now_sec
        state.horizontal_duration_sec = 0.0
        state.pose_duration_sec = 0.0
        state.recovery_duration_sec = 0.0
        # 진단 전용(평가 프로토콜 V2) — Event schema에는 넣지 않는다. dynamic
        # 근거가 있으면 그게 우선 사유고, 없는데도 여기 도달했다면
        # _model_candidate_ready()만으로 들어온 것이므로 "model"이다.
        state.candidate_entry_reason = "dynamic" if is_dynamic else "model"
        # model_fall_evidence/model_duration_sec은 초기화하지 않는다 — NORMAL
        # 상태에서 이미 쌓인 근거가 candidate 진입 이후 confirm 판정에도 그대로
        # 이어져야 한다 (모듈 docstring). single-frame confirm은
        # model_candidate_entry_sec < model_confirm_sec 관계로 막는다.
        state.max_descent_score = self._descent_score(features)

    def _model_candidate_ready(self, state: _TrackState) -> bool:
        return state.model_duration_sec >= self.config.model_candidate_entry_sec

    def _advance_candidate(
        self,
        state: _TrackState,
        features: FallFeatures,
        pose_features: Optional[PoseFeatures],
        step_dt: float,
        now_sec: float,
        track: Track,
        frame_number: int,
        video_source: str,
        timestamp: str,
        cause_attributor: Optional[FallCauseAttributor],
        diagnostics: Optional[List[dict]] = None,
    ) -> Optional[Event]:
        cfg = self.config
        # model_duration_sec은 _advance_state에서 이미 갱신됐다(recovery 판단보다
        # 먼저 갱신돼야 하는 이유는 모듈 docstring 참고).
        model_active = state.model_duration_sec > 0.0

        if self._is_recovered(features, pose_features, model_active):
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

        # 우선순위는 위 if 조건과 같은 순서(bbox -> pose -> model)로 둔다 — 여러
        # 경로가 동시에 임계값을 넘겨도 진단 필드에는 하나만 남겨야 하므로,
        # 실제 판정에 쓰인 조건과 동일한 순서로 어느 경로가 confirm시켰는지
        # 결정한다. 이 값은 진단 전용이며 Event에는 포함되지 않는다.
        confirm_path: Optional[str] = None
        if state.horizontal_duration_sec >= cfg.fall_confirm_sec:
            confirm_path = "bbox"
        elif state.pose_duration_sec >= cfg.fall_confirm_sec:
            confirm_path = "pose"
        elif state.model_duration_sec >= cfg.model_confirm_sec:
            confirm_path = "model"

        if confirm_path is not None:
            return self._confirm_fall(
                state,
                features,
                now_sec,
                track,
                frame_number,
                video_source,
                timestamp,
                cause_attributor,
                diagnostics,
                confirm_path,
            )

        if (
            state.candidate_since_sec is not None
            and now_sec - state.candidate_since_sec >= cfg.fall_candidate_timeout_sec
        ):
            # 세 confirm 경로(수평 자세/pose/모델) 모두 충분히 지속되지 못한 채
            # candidate 상태가 너무 길어지면 (예: 서 있지도 눕지도 않은 애매한
            # 자세가 지속) NORMAL로 되돌린다.
            self._reset_to_normal(state)
        return None

    def _accumulate_model_duration(
        self,
        state: _TrackState,
        model_evidence: Optional[FallModelEvidence],
        step_dt: float,
        now_sec: float,
    ) -> None:
        """bounded temporal voting: 최근 model_vote_window_sec 구간 안에서

        label="fall"이었던 시간의 합을 model_duration_sec에 반영한다 (모듈
        docstring 참고).

        model_evidence가 None(모델을 쓰지 않음)이면 근거 목록과
        model_duration_sec을 모두 비운다 — None은 "이 경로를 완전히
        비활성화한다"는 계약이므로, candidate 진행 중에 (예: 모델 로딩 실패로)
        갑자기 None으로 바뀌어도 이전에 쌓인 근거가 남아 있으면 안 된다.
        label="fall"이면 이번 스텝을 근거 목록에 추가한다. label="nofall"·
        "unknown"은 근거를 추가하지 않지만 기존 근거를 즉시 지우지도 않는다
        — 윈도우를 벗어나야(오래돼야) 자연스럽게 제거된다.
        """
        if model_evidence is None:
            state.model_fall_evidence = []
            state.model_duration_sec = 0.0
            return

        if model_evidence.label == "fall":
            state.model_fall_evidence.append((now_sec, step_dt))

        window_start = now_sec - self.config.model_vote_window_sec
        state.model_fall_evidence = [
            (ts, dt) for ts, dt in state.model_fall_evidence if ts > window_start
        ]
        state.model_duration_sec = sum(dt for _, dt in state.model_fall_evidence)

    def _advance_cooldown(
        self,
        state: _TrackState,
        features: FallFeatures,
        pose_features: Optional[PoseFeatures],
        model_evidence: Optional[FallModelEvidence],
        step_dt: float,
        now_sec: float,
    ) -> None:
        # Cooldown 만료 후에도 쓰러진 근거가 남으면 유지한다. Candidate와
        # 동일한 회복 debounce를 사용해 단일 unknown 프레임의 재확정을 막는다.
        cfg = self.config
        if now_sec < (state.cooldown_until_sec or 0.0):
            state.recovery_duration_sec = 0.0
            return

        # model_duration_sec은 _advance_state에서 이미 갱신됐다(모듈 docstring,
        # _advance_candidate와 동일한 이유).
        model_active = state.model_duration_sec > 0.0
        if not self._is_recovered(features, pose_features, model_active):
            state.recovery_duration_sec = 0.0
            return

        state.recovery_duration_sec += step_dt
        if state.recovery_duration_sec < cfg.recovery_confirm_sec:
            return

        state.state = _STATE_NORMAL
        state.cooldown_until_sec = None
        state.recovery_duration_sec = 0.0
        # cooldown 중에도 모델 근거는 계속 쌓인다(모듈 docstring, 상태 무관
        # 수집). NORMAL로 막 전이한 시점에 cooldown 막바지의 잔여 근거로
        # 곧바로 model-assisted candidate 진입이 일어나지 않도록 비운다.
        state.model_fall_evidence = []
        state.model_duration_sec = 0.0
        # Cooldown Handoff로 승계받았다면 origin_track_ids가 남아있을 수
        # 있다 — 여기서 비우지 않으면, 이 Track이 이후 완전히 새로운
        # 낙상으로 confirm될 때 이전 낙상의 alias가 cause attribution
        # victim_track_id_aliases에 잘못 섞여 들어간다(_confirm_fall은
        # 원래 candidate 진입부터 시작하는 경로만 가정하고 이 필드를
        # 리셋하므로, 여기서도 같은 불변식을 지켜야 한다).
        state.origin_track_ids = frozenset()

    def _reset_to_normal(self, state: _TrackState) -> None:
        state.state = _STATE_NORMAL
        state.candidate_since_sec = None
        state.horizontal_duration_sec = 0.0
        state.pose_duration_sec = 0.0
        state.recovery_duration_sec = 0.0
        state.model_fall_evidence = []
        state.model_duration_sec = 0.0
        state.last_processed_sec = None
        state.max_descent_score = 0.0
        state.candidate_entry_reason = None
        state.origin_track_ids = frozenset()

    def _confirm_fall(
        self,
        state: _TrackState,
        features: FallFeatures,
        now_sec: float,
        track: Track,
        frame_number: int,
        video_source: str,
        timestamp: str,
        cause_attributor: Optional[FallCauseAttributor],
        diagnostics: Optional[List[dict]] = None,
        confirm_path: Optional[str] = None,
    ) -> Event:
        event_confidence = self._compute_event_confidence(features, state)
        # fall_start_sec(onset proxy)은 FALLING_CANDIDATE 진입 시각이다. 아래
        # cleanup에서 state.candidate_since_sec을 None으로 리셋하므로, attribution에
        # 넘기기 전에 반드시 로컬 변수로 먼저 꺼내둔다 — 순서를 바꾸면 항상
        # None이 들어가 cause가 절대 채워지지 않는다 (모듈 docstring 참고).
        fall_start_sec = state.candidate_since_sec
        candidate_entry_reason = state.candidate_entry_reason
        # cleanup에서 state.origin_track_ids를 비우므로(아래), attribution에
        # 넘기기 전에 먼저 로컬 변수로 꺼내둔다 — fall_start_sec과 같은 이유
        # 승계 이전 이력까지 attribution에 전달하기 위해 먼저 보존한다.
        origin_track_ids = state.origin_track_ids

        if diagnostics is not None:
            diagnostics.append(
                {
                    "video_source": video_source,
                    "track_id": track.track_id,
                    "frame_number": frame_number,
                    "confirm_path": confirm_path,
                    "candidate_entry_reason": candidate_entry_reason,
                }
            )

        state.state = _STATE_COOLDOWN
        state.cooldown_until_sec = now_sec + self.config.cooldown_sec
        state.candidate_since_sec = None
        state.horizontal_duration_sec = 0.0
        state.pose_duration_sec = 0.0
        state.recovery_duration_sec = 0.0
        state.model_fall_evidence = []
        state.model_duration_sec = 0.0
        state.last_processed_sec = None
        state.max_descent_score = 0.0
        state.candidate_entry_reason = None
        state.origin_track_ids = frozenset()

        self._cooldown_tombstones.setdefault(video_source, []).append(
            _CooldownTombstone(bbox=list(track.bbox), cooldown_until_sec=state.cooldown_until_sec)
        )

        cause: Optional[EventCause] = None
        if cause_attributor is not None:
            # cause는 이미 확정된 낙상에 덧붙이는 부가 정보다 — 이 호출이
            # 예외를 내더라도 핵심 FALL_SUSPECT Event 자체(위에서 이미
            # COOLDOWN 전이와 tombstone 기록까지 끝났다)는 반드시 반환돼야
            # 한다. fail-closed: 예외는 로그로 남기고 cause=None으로 진행한다.
            try:
                cause = cause_attributor.attribute(
                    video_source=video_source,
                    victim_track_id=track.track_id,
                    fall_start_sec=fall_start_sec,
                    victim_track_id_aliases=origin_track_ids,
                )
            except Exception:
                LOGGER.exception(
                    "cause attribution 실패(track_id=%s, video_source=%s) — "
                    "cause=None으로 진행합니다.",
                    track.track_id,
                    video_source,
                )
                cause = None

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
            cause=cause,
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
        self,
        features: FallFeatures,
        pose_features: Optional[PoseFeatures],
        model_active: bool = False,
    ) -> bool:
        # pose가 쓰러진 자세로 보거나 모델 경로가 활성(label="fall" 또는 grace
        # 이내 "unknown")인 동안에는 회복으로 보지 않는다. aspect_ratio가 낮게
        # 유지되는 낙상(모듈 docstring 참고)에서 회복 조건이 자주 만족돼
        # pose/모델 confirm 진행이 중간에 끊기는 문제를 막기 위함이다.
        # model_active는 호출자가 model_duration_sec을 먼저 갱신한 뒤 넘겨야
        # 한다 (모듈 docstring, _advance_candidate 참고).
        if pose_features is not None and pose_features.is_fallen_pose:
            return False
        if model_active:
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
        # 세 confirm 경로(수평 자세/pose/모델) 중 각자의 목표 대비 가장 많이
        # 진행된 비율을 지속시간 점수로 쓴다 (model_confirm_sec이 fall_confirm_sec와
        # 다를 수 있으므로 절대 시간이 아니라 비율로 비교한다).
        duration_ratios = [0.0]
        if cfg.fall_confirm_sec > 0:
            duration_ratios.append(state.horizontal_duration_sec / cfg.fall_confirm_sec)
            duration_ratios.append(state.pose_duration_sec / cfg.fall_confirm_sec)
        if cfg.model_confirm_sec > 0:
            duration_ratios.append(state.model_duration_sec / cfg.model_confirm_sec)
        duration_score = min(1.0, max(duration_ratios))
        track_confidence_score = features.avg_confidence

        score = (
            weights.get("posture", 0.0) * posture_score
            + weights.get("descent", 0.0) * descent_score
            + weights.get("duration", 0.0) * duration_score
            + weights.get("track_confidence", 0.0) * track_confidence_score
        )
        return max(0.0, min(1.0, score))
