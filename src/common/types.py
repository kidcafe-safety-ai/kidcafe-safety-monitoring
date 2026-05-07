"""
공통 데이터 타입 정의.
모든 모듈이 이 타입을 import해서 사용합니다.
"""

from dataclasses import dataclass, field
from typing import List, Literal
from datetime import UTC, datetime
import uuid


# ============ Tracking 결과 ============

@dataclass
class Track:
    """한 프레임에서 감지된 한 명의 사람."""
    track_id: int
    bbox: List[float]            # [x1, y1, x2, y2]
    foot_point: List[float]      # [cx, y2]
    confidence: float            # 0.0 ~ 1.0
    
    def __post_init__(self):
        if not isinstance(self.track_id, int) or self.track_id < 0:
            raise ValueError(f"track_id must be non-negative int")
        if len(self.bbox) != 4:
            raise ValueError(f"bbox must have 4 elements")
        if len(self.foot_point) != 2:
            raise ValueError(f"foot_point must have 2 elements")
        if not (0 <= self.confidence <= 1.0):
            raise ValueError(f"confidence must be in [0, 1]")
    
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
    timestamp: str               # ISO 8601
    video_source: str
    tracks: List[Track] = field(default_factory=list)


# ============ Geofencing 입력 ============

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
    type: Literal["polygon", "circle"]
    points: List[List[float]]          # 정규화 좌표 (0~1)
    rules: ZoneRules = field(default_factory=ZoneRules)
    
    def __post_init__(self):
        if not self.zone_id:
            raise ValueError("zone_id cannot be empty")
        if self.type not in ["polygon", "circle"]:
            raise ValueError(f"type must be 'polygon' or 'circle'")
        if len(self.points) < 3 and self.type == "polygon":
            raise ValueError(f"polygon must have at least 3 points")


# ============ Geofencing 출력 ============

EventType = Literal["ENTER", "DWELL", "EXIT"]


@dataclass
class Event:
    """위험구역 이벤트."""
    event_id: str
    timestamp: str
    event_type: EventType
    track_id: int
    zone_id: str
    bbox: List[float]
    foot_point: List[float]
    frame_number: int
    video_source: str
    
    def __post_init__(self):
        if len(self.bbox) != 4:
            raise ValueError(f"bbox must have 4 elements")
        if len(self.foot_point) != 2:
            raise ValueError(f"foot_point must have 2 elements")
    
    @staticmethod
    def create(
        event_type: EventType,
        track_id: int,
        zone_id: str,
        bbox: List[float],
        foot_point: List[float],
        frame_number: int,
        video_source: str,
        timestamp: str = None
    ) -> "Event":
        """Event 생성 헬퍼."""
        if timestamp is None:
            timestamp = datetime.now(UTC).isoformat()
        
        return Event(
            event_id=str(uuid.uuid4()),
            timestamp=timestamp,
            event_type=event_type,
            track_id=track_id,
            zone_id=zone_id,
            bbox=bbox,
            foot_point=foot_point,
            frame_number=frame_number,
            video_source=video_source
        )