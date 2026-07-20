"""FALL_SUSPECT 상태머신 및 감지기.

계약: docs/interfaces.md FALL_SUSPECT·EventCause 계약
(상태 흐름 NORMAL → FALLING_CANDIDATE → (FALL_CONFIRMED) → COOLDOWN → NORMAL,
FALL_CONFIRMED는 지속 상태가 아니라 momentary transition).

Track별로 독립된 상태머신을 유지하며, confirm 전이 시에만 Track당 1개의
FALL_SUSPECT Event를 생성한다. cause는 이 클래스가 직접 만들지 않는다 —
process()에 cause_attributor(FallCauseAttributor)를 넘기면 confirm 시점에
그 인스턴스의 attribute()를 호출해 cause를 채우고, 넘기지 않으면(기본값
None) 항상 None이다(ADR-016, src/safety/fall_cause_attributor.py 모듈
docstring 참고). 외부 접촉 원인 후보 추정 로직 자체는 이 파일의 책임이
아니다 — 근접 이력 관리·점수 계산은 전부 FallCauseAttributor가 소유한다.

각 메커니즘의 설계 배경·튜닝 실험·Subject별 실측 수치는 코드가 아니라
docs/fall_evaluation.md에 둔다(문서 구조가 바뀌어도 이 파일이 깨지지 않도록
번호 참조 없이 "docs/fall_evaluation.md 참고"로만 가리킨다). 아래는 각
메커니즘이 무엇을 하는지에 대한 요약이다.

candidate 진입과 confirm은 서로 다른 근거를 쓴다: candidate 진입은 하강
속도 또는 높이 수축률 중 하나(동적 근거)만으로 충분하고, confirm은
candidate 진입 이후 수평 자세(aspect_ratio)가 fall_confirm_sec 이상
지속돼야 한다 — 두 조건을 분리한 이유와 대체 신호 검토·폐기 과정은
docs/fall_evaluation.md 참고.

Pose 보완: PoseTracker(yolo26n-pose.pt)가 Track.keypoints를 채워주면 confirm에
pose 기반 경로(머리-엉덩이 상대 높이, `PoseFeatures.head_hip_diff_norm`)를
수평 자세 경로와 OR로 추가한다. keypoints가 없는 Track(ByteTracker 사용
시)은 pose 경로가 항상 None을 반환해 자동으로 비활성화되므로 기존 bbox
전용 동작과 완전히 하위 호환된다. recovery 판정은 pose가 "쓰러진 자세"로
보는 동안에는 성립하지 않으며, 단일 프레임이 아니라 recovery_confirm_sec
이상 지속돼야 실제로 NORMAL로 되돌린다(검출 jitter로 candidate가 바로
초기화되지 않도록). pose 신호가 일시적으로 없는 프레임에서는
pose_duration_sec을 0으로 초기화하지 않고 유지하며,
fall_candidate_timeout_sec가 candidate 전체의 상한을 건다.

fine-tuned fall/nofall 모델 보완: 보조 모델 자체는 이 클래스가 소유하지
않는다 — 자체 추적을 하지 않는 detector이므로 Track ID를 IoU로 매칭하는
전처리(src/safety/fall_model_matching.py)가 process() 호출 전에 별도로
필요하고, 그 결과인 FallModelEvidence를 Track별로 process()에 선택적으로
전달한다. evidence를 아예 전달하지 않으면(model_evidence=None) 이 경로는
완전히 비활성화되어 기존 bbox/pose 전용 동작과 하위 호환된다.

model confirm 경로는 bounded temporal voting을 쓴다: 최근
model_vote_window_sec(기본 0.5초) 동안의 판단만 보관하고, 그 구간 안에서
label="fall"로 관측된 시간의 합이 model_confirm_sec(기본 0.2초) 이상이면
confirm 조건을 만족한다(`_TrackState.model_fall_evidence`,
`_accumulate_model_duration`). 단순 연속 지속시간 누적 대신 이 방식을 쓴
이유(간헐적 오검출로 인한 Event Recall 저하)는 docs/fall_evaluation.md
참고. 규칙:
    - label="fall": 이번 스텝의 시간을 근거 목록에 추가한다.
    - label="nofall"/"unknown": 근거를 추가하지 않지만 이미 쌓인 근거를
      즉시 삭제하지도 않는다.
    - model_vote_window_sec보다 오래된 근거는 매 스텝 자동으로 제거된다.
    - model_evidence 자체가 None(모델 완전 비활성화)이면 근거 목록을
      즉시 비운다 — "이 경로를 완전히 비활성화한다"는 계약이기 때문이다.

recovery 판정은 model_duration_sec을 먼저 갱신한 뒤 계산한다(순서를
반대로 하면 윈도우 안에 남아있는 근거가 무시된 채 candidate가 리셋된다).
cooldown 판정도 pose와 동일하게 model이 "fall"로 보는 동안에는 조기
재진입 방지 대상에 포함시킨다.

cooldown 중 Track 소실 시에도 COOLDOWN 상태를 유지한다 — `_forget_lost_tracks()`가
COOLDOWN 상태의 Track은 MultiTrackHistory의 grace period가 지나 사라져도
`_states`에서 지우지 않는다(지우면 짧은 소실 뒤 재검출 시 cooldown 기억이
사라져 같은 낙상을 다시 candidate로 잡는다). 이 보존은 cooldown_until_sec
까지만이다 — 그 시각이 지난 뒤에도 계속 소실 상태면 `_forget_lost_tracks()`가
함께 지운다(실시간 스트림에서 상태가 낙상마다 무기한 누적되는 것을 막기
위함). cooldown 만료 전에 Track이 다시 나타나면 `_advance_cooldown()`이
정상적으로 NORMAL로 되돌린다.

model 기반 candidate 진입: ByteTrack/PoseTracker는 ReID가 없어 낙상 순간
Track을 놓치고 재검출 시 새 track_id를 부여하는 경우가 흔하다 — 재검출된
새 Track은 이미 쓰러져 정지한 상태로 시작하므로 candidate 진입에 필요한
bbox 동적 근거가 애초에 발생하지 않는다(실측 사례는 docs/fall_evaluation.md
참고). 이를 해결하기 위해 candidate 진입 조건에 모델 경로를 OR로 추가한다:
윈도우 내 누적 label="fall" 시간이 model_candidate_entry_sec(기본 0.1초,
model_confirm_sec보다 반드시 작아야 함 — __post_init__에서 검증) 이상이면
bbox 동적 근거 없이도 candidate에 진입한다. 정식 ReID(Track 재연결)는
Phase 4로 미룬다.

모델 근거 수집 자체는 상태와 무관하게 매 프레임 갱신한다(`_advance_state`
최상단, `_accumulate_model_duration`) — NORMAL 상태에서도 쌓여야
model-assisted 진입 판정을 할 수 있기 때문이다. candidate 진입 시 더 이상
model_fall_evidence를 비우지 않는다 — NORMAL에서 쌓인 근거가 candidate
진입 이후 confirm 판정에도 그대로 이어져야 하기 때문이다(단일 프레임만으로
confirm되지 않도록 model_confirm_sec > model_candidate_entry_sec 관계로
최소 한 스텝 이상의 추가 근거를 강제한다).

공간 기반 cooldown 승계: model-assisted candidate 진입이 Recall을 끌어올리며
드러난 또 다른 ReID 부재 문제(낙상 confirm 후 같은 사람이 새 track_id로
재검출되면 원래 track의 cooldown을 전혀 모른 채 스스로 candidate→confirm까지
진행해 같은 물리적 낙상이 두 번 확정됨, 실측 사례는 docs/fall_evaluation.md
참고)에 대한 대응이다. 정식 ReID(외형 특징 기반)는 Phase 4로 미루고, 여기서는
순수 위치(IoU) 기반의 경량 승계만 추가한다: Track이 confirm될 때 그 bbox와
cooldown_until_sec을 `_cooldown_tombstones`(video_source별)에 남긴다. 새
`_TrackState`가 생성되는 시점에, 같은 video_source의 만료되지 않은 tombstone
중 현재 bbox와 IoU가 cooldown_inherit_iou_threshold 이상인 것이 있으면 새
Track은 NORMAL이 아니라 그 tombstone의 남은 cooldown을 물려받은 COOLDOWN
상태로 시작한다(`_try_inherit_cooldown`). 다른 위치의 Track은 영향받지
않는다. 만료된 tombstone은 매 프레임 정리된다.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

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


@dataclass(frozen=True)
class _CooldownTombstone:
    """confirm된 Track이 남기는 흔적 — 공간 기반 cooldown 승계에 쓴다 (모듈 docstring)."""

    bbox: List[float]
    cooldown_until_sec: float


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

    def process(
        self,
        tracking_result: TrackingResult,
        model_evidence: Optional[Dict[int, FallModelEvidence]] = None,
        cause_attributor: Optional[FallCauseAttributor] = None,
    ) -> List[Event]:
        """한 프레임의 TrackingResult를 반영하고, FALL_CONFIRMED 전이가 있으면 Event를 반환한다.

        model_evidence: track_id -> FallModelEvidence. fine-tuned fall/nofall 모델을
            쓰지 않으면(호출자가 AuxiliaryFallModel을 아예 안 쓰거나 enabled=False)
            None으로 두면 된다 — model confirm 경로가 완전히 비활성화되어 기존
            bbox/pose 전용 동작과 하위 호환된다. 이 딕셔너리를 만드는 IoU 매칭은
            이 클래스의 책임이 아니다 (src/safety/fall_model_matching.py).
        cause_attributor: 지정하면 confirm 시 FallCauseAttributor.attribute()를
            호출해 EventCause를 채운다. None이면(기본값, 기존 호출과 하위 호환)
            cause는 항상 None이다 — PR2 동작과 완전히 동일하다.
        """
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
    ) -> Optional[Event]:
        is_new_track = key not in self._states
        state = self._states.setdefault(key, _TrackState())
        if is_new_track:
            # 공간 기반 cooldown 승계(모듈 docstring) — ReID 없이 재획득된
            # 같은 사람이 곧바로 새 candidate/confirm을 만들지 않도록, 이
            # video_source의 최근 confirm 위치와 겹치는지 먼저 확인한다.
            self._try_inherit_cooldown(state, track, video_source, now_sec)

        # step_dt 계산과 모델 근거 갱신은 상태와 무관하게 매 프레임 한 번만
        # 수행한다(모듈 docstring, model 기반 candidate 진입 참고) — NORMAL
        # 상태에서도 근거가 쌓여야 model-assisted 진입 판정을 할 수 있다.
        # last_processed_sec을 여기서 먼저 읽어 step_dt를 구한 뒤에 갱신해야
        # 하므로, 각 분기 함수는 더 이상 스스로 step_dt를 계산하거나
        # last_processed_sec을 건드리지 않는다.
        step_dt = self._visible_step_dt(state, now_sec)
        self._accumulate_model_duration(state, model_evidence, step_dt, now_sec)
        state.last_processed_sec = now_sec

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
            )

        if state.state == _STATE_COOLDOWN:
            self._advance_cooldown(state, features, pose_features, model_evidence, now_sec)
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
        if not self._dynamic_evidence(features) and not self._model_candidate_ready(state):
            return
        state.state = _STATE_FALLING_CANDIDATE
        state.candidate_since_sec = now_sec
        state.horizontal_duration_sec = 0.0
        state.pose_duration_sec = 0.0
        state.recovery_duration_sec = 0.0
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

        if (
            state.horizontal_duration_sec >= cfg.fall_confirm_sec
            or state.pose_duration_sec >= cfg.fall_confirm_sec
            or state.model_duration_sec >= cfg.model_confirm_sec
        ):
            return self._confirm_fall(
                state,
                features,
                now_sec,
                track,
                frame_number,
                video_source,
                timestamp,
                cause_attributor,
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
        now_sec: float,
    ) -> None:
        # cooldown 만료 후에도 누워 있으면 재감지하지 않고, 회복 자세 확인 후 NORMAL로 전이한다.
        # bbox(is_horizontal_posture)만 보면 깊이 방향 낙상에서 pose는 여전히
        # 쓰러진 자세인데도 조기에 NORMAL로 전이해 같은 낙상을 다시 candidate로
        # 잡아 중복 Event를 만드는 문제가 있었다(S4_fall_forward 실측). recovery
        # 판정(_is_recovered)과 동일하게 pose·모델이 쓰러진 자세/fall로 보는 동안에는
        # 회복으로 보지 않는다.
        still_fallen = (
            features.is_horizontal_posture
            or (pose_features is not None and pose_features.is_fallen_pose)
            or (model_evidence is not None and model_evidence.label == "fall")
        )
        if now_sec >= (state.cooldown_until_sec or 0.0) and not still_fallen:
            state.state = _STATE_NORMAL
            state.cooldown_until_sec = None
            # cooldown 중에도 모델 근거는 계속 쌓인다(모듈 docstring, 상태 무관
            # 수집). NORMAL로 막 전이한 시점에 cooldown 막바지의 잔여 근거로
            # 곧바로 model-assisted candidate 진입이 일어나지 않도록 비운다.
            state.model_fall_evidence = []
            state.model_duration_sec = 0.0

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
    ) -> Event:
        event_confidence = self._compute_event_confidence(features, state)
        # fall_start_sec(onset proxy)은 FALLING_CANDIDATE 진입 시각이다. 아래
        # cleanup에서 state.candidate_since_sec을 None으로 리셋하므로, attribution에
        # 넘기기 전에 반드시 로컬 변수로 먼저 꺼내둔다 — 순서를 바꾸면 항상
        # None이 들어가 cause가 절대 채워지지 않는다 (모듈 docstring 참고).
        fall_start_sec = state.candidate_since_sec

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
