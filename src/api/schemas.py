"""Pydantic schemas for Event API v1."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


EventType = Literal["ENTER", "DWELL", "EXIT"]
RiskLevel = Literal["NORMAL", "HIGH"]
TIMESTAMP_REGEX = r"^\d{2}:[0-5]\d:[0-5]\d\.\d{3}$"
TIMESTAMP_PATTERN = re.compile(TIMESTAMP_REGEX)


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


class ZonesResponse(BaseModel):
    status: Literal["success"]
    data: List[Dict[str, Any]]
    message: None = None


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
