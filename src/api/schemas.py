"""Pydantic schemas for Event API v1."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.geofencing.polygon_rules import validate_polygon_points


EventType = Literal[
    "ENTER",
    "DWELL",
    "EXIT",
    "ENTER_RESTRICTED",
    "DANGER_ZONE_DWELL",
    "FALL_SUSPECT",
]
RiskLevel = Literal["NORMAL", "HIGH"]
EventCauseType = Literal["NEARBY_TRACK"]
TIMESTAMP_REGEX = r"^\d{2}:[0-5]\d:[0-5]\d\.\d{3}$"
TIMESTAMP_PATTERN = re.compile(TIMESTAMP_REGEX)


class EventCauseEvidence(BaseModel):
    min_distance_norm: float = Field(ge=0.0)
    closing_speed_norm: float = Field(ge=0.0)
    time_to_fall_sec: float = Field(ge=0.0)


class EventCause(BaseModel):
    """부분 필드만 채운 cause는 허용하지 않는다 (모든 필드 필수)."""

    type: EventCauseType
    track_id: int = Field(ge=0)
    score: float = Field(ge=0.0, le=1.0)
    evidence: EventCauseEvidence


class EventCreate(BaseModel):
    event_id: str
    timestamp: str = Field(pattern=TIMESTAMP_REGEX)
    event_type: EventType
    track_id: int
    zone_id: str
    bbox: List[float] = Field(min_length=4, max_length=4)
    foot_point: List[float] = Field(min_length=2, max_length=2)
    frame_number: int
    video_source: str
    zone_name: Optional[str] = None
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    event_confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    cause: Optional[EventCause] = None

    @field_validator("timestamp")
    @classmethod
    def validate_timestamp(cls, value: str) -> str:
        if not TIMESTAMP_PATTERN.match(value):
            raise ValueError("timestamp must match HH:MM:SS.mmm")
        return value


class EventOut(BaseModel):
    id: int
    event_id: str
    timestamp: str
    event_type: EventType
    track_id: int
    zone_id: str
    zone_name: Optional[str]
    bbox: List[float]
    foot_point: List[float]
    frame_number: int
    video_time_sec: Optional[float]
    confidence: Optional[float]
    event_confidence: Optional[float] = None
    cause: Optional[EventCause] = None
    video_source: str
    created_at: str


class EventListData(BaseModel):
    items: List[EventOut]
    total: int
    limit: int
    offset: int
    count: int


class SummaryData(BaseModel):
    total_events: int
    today_event_count: int
    recent_10min_event_count: int
    enter_count: int
    dwell_count: int
    exit_count: int
    total_tracks: int
    video_count: int
    avg_dwell_seconds: float


class CurrentZoneOccupancy(BaseModel):
    zone_id: str = Field(min_length=1)
    zone_name: Optional[str] = None
    current_count: int = Field(ge=0)
    risk_level: RiskLevel


class CurrentStatusCreate(BaseModel):
    source: str = Field(min_length=1)
    frame_number: int = Field(ge=0)
    active_track_count: int = Field(ge=0)
    zone_occupancy: List[CurrentZoneOccupancy]
    updated_at: Optional[str] = None


class CurrentStatusOut(BaseModel):
    source: str
    frame_number: int
    active_track_count: int
    zone_occupancy: List[CurrentZoneOccupancy]
    updated_at: Optional[str] = None


class CurrentStatusUpdateData(BaseModel):
    source: str
    updated: bool


class HealthData(BaseModel):
    service: str
    healthy: bool


class HealthResponse(BaseModel):
    status: Literal["success"]
    data: HealthData
    message: None = None


class EventResponse(BaseModel):
    status: Literal["success"]
    data: EventOut
    message: None = None


class EventListResponse(BaseModel):
    status: Literal["success"]
    data: EventListData
    message: None = None


class EventRecentResponse(BaseModel):
    status: Literal["success"]
    data: List[EventOut]
    message: None = None


class SummaryResponse(BaseModel):
    status: Literal["success"]
    data: SummaryData
    message: None = None


class CurrentStatusUpdateResponse(BaseModel):
    status: Literal["success"]
    data: CurrentStatusUpdateData
    message: None = None


class CurrentStatusResponse(BaseModel):
    status: Literal["success"]
    data: CurrentStatusOut
    message: None = None


ZoneTypeName = Literal["play", "exit", "restricted", "danger"]

VERSION_PATTERN = r"^sha256:[0-9a-f]{64}$"


class ZoneRulesPayload(BaseModel):
    # strict: Pydantic 기본 coercion은 "false"를 False로, "5"를 5로 바꾼다.
    # 동결 계약은 boolean·integer를 요구하므로 잘못된 타입은 422여야 한다.
    model_config = ConfigDict(strict=True)

    enter_alert: bool
    dwell_threshold_sec: int = Field(ge=0, le=3600)


class ZonePayload(BaseModel):
    """`PUT /zones` 요청과 응답의 Zone 표현. API는 `zone_name`을 사용한다.

    strict 모드라 문자열·boolean 좌표를 number로 자동 변환하지 않는다. JSON 정수
    좌표(`[0, 1]`)는 float으로 받아들인다.
    """

    model_config = ConfigDict(strict=True)

    zone_id: str = Field(min_length=1)
    zone_name: str = Field(min_length=1)
    type: Literal["polygon"]
    zone_type: ZoneTypeName
    points: List[List[float]]
    rules: ZoneRulesPayload

    @field_validator("zone_id", "zone_name")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value

    @field_validator("points")
    @classmethod
    def _valid_polygon(cls, value: List[List[float]]) -> List[List[float]]:
        # Vision AI의 floor Zone과 같은 규칙을 쓴다 (src/geofencing/polygon_rules.py).
        return validate_polygon_points(value, coordinate_range=(0.0, 1.0))


class ZoneConfigData(BaseModel):
    version: str = Field(pattern=VERSION_PATTERN)
    updated_at: str
    zones: List[ZonePayload]


class ZonesResponse(BaseModel):
    status: Literal["success"]
    data: ZoneConfigData
    message: None = None


class PutZonesRequest(BaseModel):
    """전체 Zone 목록을 교체한다. 누락한 Zone은 삭제 대상으로 해석한다."""

    model_config = ConfigDict(strict=True)

    expected_version: str = Field(pattern=VERSION_PATTERN)
    zones: List[ZonePayload]

    @field_validator("zones")
    @classmethod
    def _unique_zone_ids(cls, value: List[ZonePayload]) -> List[ZonePayload]:
        seen = set()
        for zone in value:
            if zone.zone_id in seen:
                raise ValueError(f"duplicate zone_id: {zone.zone_id}")
            seen.add(zone.zone_id)
        return value


class ErrorResponse(BaseModel):
    status: Literal["error"]
    data: None = None
    message: str


class ApiResponse(BaseModel):
    status: str
    data: Any
    message: Optional[str] = None


def success_response(data: Any) -> Dict[str, Any]:
    return {"status": "success", "data": data, "message": None}


def error_response(message: str) -> Dict[str, Any]:
    return {"status": "error", "data": None, "message": message}


def timestamp_to_seconds(value: str) -> float:
    hours = int(value[0:2])
    minutes = int(value[3:5])
    seconds = int(value[6:8])
    milliseconds = int(value[9:12])
    return hours * 3600 + minutes * 60 + seconds + milliseconds / 1000.0
