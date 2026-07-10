"""
공통 데이터 타입 정의.
모든 모듈이 이 타입을 import해서 사용합니다.

timestamp 형식 표준:
    - 형식: "HH:MM:SS.mmm"
    - 의미: 영상 내 상대 시각 (시스템 시간 아님)
    - 계산: frame_number / fps
    - 참고: docs/decisions.md ADR-005
"""

import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional

# ============ Tracking 결과 ============


@dataclass
class Track:
    """한 프레임에서 감지된 한 명의 사람."""

    track_id: int
    bbox: List[float]  # [x1, y1, x2, y2] pixel 좌표
    foot_point: List[float]  # [cx, y2] pixel 좌표
    confidence: float  # 0.0 ~ 1.0

    def __post_init__(self):
        if not isinstance(self.track_id, int) or self.track_id < 0:
            raise ValueError("track_id must be non-negative int")
        if len(self.bbox) != 4:
            raise ValueError("bbox must have 4 elements")
        if len(self.foot_point) != 2:
            raise ValueError("foot_point must have 2 elements")
        if not (0 <= self.confidence <= 1.0):
            raise ValueError("confidence must be in [0, 1]")

    @property
    def width(self) -> float:
        return self.bbox[2] - self.bbox[0]

    @property
    def height(self) -> float:
        return self.bbox[3] - self.bbox[1]

    @property
    def area(self) -> float:
        return self.width * self.height


@dataclass
class TrackingResult:
    """한 프레임의 모든 추적 결과."""

    frame_number: int
    timestamp: str  # "HH:MM:SS.mmm" 영상 내 상대 시각
    video_source: str
    tracks: List[Track] = field(default_factory=list)


# ============ Geofencing 입력 ============

ZoneType = Literal["play", "exit", "restricted", "danger"]
VALID_ZONE_TYPES = {"play", "exit", "restricted", "danger"}


@dataclass
class ZoneRules:
    """구역의 규칙."""

    enter_alert: bool = True
    dwell_threshold_sec: int = 5


@dataclass
class Zone:
    """위험구역 정의."""

    zone_id: str
    name: str
    type: Literal["polygon"]
    zone_type: ZoneType
    points: List[List[float]]  # 정규화 좌표 (0~1)
    rules: ZoneRules = field(default_factory=ZoneRules)

    def __post_init__(self):
        if not self.zone_id:
            raise ValueError("zone_id cannot be empty")
        if self.type != "polygon":
            raise ValueError("type must be 'polygon'")
        if self.zone_type not in VALID_ZONE_TYPES:
            raise ValueError(
                f"zone_type must be one of {VALID_ZONE_TYPES}, got '{self.zone_type}'"
            )
        if len(self.points) < 3:
            raise ValueError("polygon must have at least 3 points")

        for pt in self.points:
            if len(pt) != 2:
                raise ValueError("each point must have 2 elements")
            x, y = pt
            if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
                raise ValueError("zone points must be normalized in [0, 1]")


# ============ Geofencing 출력 ============

EventType = Literal[
    "ENTER",
    "DWELL",
    "EXIT",
    "ENTER_RESTRICTED",
    "DANGER_ZONE_DWELL",
    "FALL_SUSPECT",
]
VALID_EVENT_TYPES = {
    "ENTER",
    "DWELL",
    "EXIT",
    "ENTER_RESTRICTED",
    "DANGER_ZONE_DWELL",
    "FALL_SUSPECT",
}

EventCauseType = Literal["NEARBY_TRACK"]


@dataclass
class EventCauseEvidence:
    """EventCause 판단에 사용한 근거 수치. 모두 0 이상의 실수."""

    min_distance_norm: float
    closing_speed_norm: float
    time_to_fall_sec: float

    def __post_init__(self):
        for field_name in ("min_distance_norm", "closing_speed_norm", "time_to_fall_sec"):
            value = getattr(self, field_name)
            if value < 0:
                raise ValueError(f"{field_name} must be >= 0, got {value}")


@dataclass
class EventCause:
    """FALL_SUSPECT의 외부 접촉 원인 후보. 근거 부족 시 Event.cause=None으로 유지한다.

    부분 필드만 채운 EventCause는 허용하지 않는다 (모든 필드 필수).
    참고: docs/interfaces.md FALL_SUSPECT·EventCause 계약, docs/decisions.md ADR-016
    """

    type: EventCauseType
    track_id: int
    score: float
    evidence: EventCauseEvidence

    def __post_init__(self):
        if self.type != "NEARBY_TRACK":
            raise ValueError(f"cause.type must be 'NEARBY_TRACK', got '{self.type}'")
        if not isinstance(self.track_id, int) or self.track_id < 0:
            raise ValueError("cause.track_id must be a non-negative int")
        if not (0.0 <= self.score <= 1.0):
            raise ValueError("cause.score must be in [0, 1]")


@dataclass
class Event:
    """위험구역 / 안전 이벤트.

    timestamp는 영상 내 상대 시각 ("HH:MM:SS.mmm" 형식).
    참고: docs/decisions.md ADR-005

    confidence / event_confidence / cause는 Phase 3에서 추가된 optional 필드로,
    기존 Phase 2.5 데이터와의 하위 호환을 위해 기본값 None을 가진다.
    """

    event_id: str
    timestamp: str  # "HH:MM:SS.mmm" 영상 내 상대 시각
    event_type: EventType
    track_id: int
    zone_id: str
    bbox: List[float]  # [x1, y1, x2, y2] pixel 좌표
    foot_point: List[float]  # [cx, y2] pixel 좌표
    frame_number: int
    video_source: str
    # Phase 3 추가 (optional, 하위 호환)
    confidence: Optional[float] = None  # detector/tracker confidence
    event_confidence: Optional[float] = None  # 안전 이벤트 판정 점수
    cause: Optional[EventCause] = None  # 외부 접촉 원인 후보 (FALL_SUSPECT 전용)

    def __post_init__(self):
        if self.event_type not in VALID_EVENT_TYPES:
            raise ValueError(
                f"event_type must be one of {VALID_EVENT_TYPES}, "
                f"got '{self.event_type}'"
            )
        if len(self.bbox) != 4:
            raise ValueError("bbox must have 4 elements")
        if len(self.foot_point) != 2:
            raise ValueError("foot_point must have 2 elements")
        if self.confidence is not None and not (0.0 <= self.confidence <= 1.0):
            raise ValueError("confidence must be in [0, 1] or None")
        if self.event_confidence is not None and not (0.0 <= self.event_confidence <= 1.0):
            raise ValueError("event_confidence must be in [0, 1] or None")
        if self.cause is not None and not isinstance(self.cause, EventCause):
            raise ValueError("cause must be an EventCause instance or None")

    @staticmethod
    def create(
        event_type: EventType,
        track_id: int,
        zone_id: str,
        bbox: List[float],
        foot_point: List[float],
        frame_number: int,
        video_source: str,
        timestamp: Optional[str] = None,
        confidence: Optional[float] = None,
        event_confidence: Optional[float] = None,
        cause: Optional[EventCause] = None,
    ) -> "Event":
        """Event 생성 헬퍼.

        Args:
            timestamp: "HH:MM:SS.mmm" 형식 영상 내 상대 시각.
                None인 경우 "00:00:00.000"으로 설정 (호출자가 영상 시각 미전달).
                정상 사용 시에는 EventManager가 항상 영상 시각을 전달함.
            confidence: detector/tracker confidence. 전달하지 않으면 None.
            event_confidence: 안전 이벤트 판정 점수. FALL_SUSPECT가 아니면 보통 None.
            cause: 외부 접촉 원인 후보. 근거 부족 시 None.
        """
        if timestamp is None:
            # 안전한 fallback: 시스템 시간 대신 dummy 영상 시각 사용
            # 시스템 시간과 영상 시간이 섞이는 사고 방지
            timestamp = "00:00:00.000"

        return Event(
            event_id=str(uuid.uuid4()),
            timestamp=timestamp,
            event_type=event_type,
            track_id=track_id,
            zone_id=zone_id,
            bbox=bbox,
            foot_point=foot_point,
            frame_number=frame_number,
            video_source=video_source,
            confidence=confidence,
            event_confidence=event_confidence,
            cause=cause,
        )


# ============ API 전송 페이로드 ============

RiskLevel = Literal["NORMAL", "HIGH"]


@dataclass
class CurrentZoneStatus:
    """PUT /status/current 페이로드 내 zone별 점유 현황."""

    zone_id: str
    zone_name: str
    current_count: int
    risk_level: RiskLevel


@dataclass
class CurrentStatus:
    """PUT /status/current 전송 페이로드.

    EventApiClient.send_current_status()의 인자로 사용한다.
    B의 Pydantic schema와 필드명/타입을 맞춰야 한다.
    """

    source: str
    frame_number: int
    active_track_count: int
    zone_occupancy: List[CurrentZoneStatus]
    updated_at: str  # ISO 8601 (시스템 시간 기준)

    def to_dict(self) -> Dict[str, Any]:
        """EventApiClient.send_current_status()에 전달할 dict 반환."""
        return {
            "source": self.source,
            "frame_number": self.frame_number,
            "active_track_count": self.active_track_count,
            "zone_occupancy": [
                {
                    "zone_id": z.zone_id,
                    "zone_name": z.zone_name,
                    "current_count": z.current_count,
                    "risk_level": z.risk_level,
                }
                for z in self.zone_occupancy
            ],
            "updated_at": self.updated_at,
        }
