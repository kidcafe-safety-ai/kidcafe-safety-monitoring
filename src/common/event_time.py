"""
이벤트 시간 처리 유틸리티.

담당 기능:
- "HH:MM:SS.mmm" 형식 timestamp를 초 단위로 변환
- frame_number / fps 기반 영상 시간 계산
- 이벤트 정렬 key 생성
- 영상 시간 구간 필터링

주의:
이 프로젝트의 Event.timestamp는 시스템 시간이 아니라
영상 내 상대 시각("HH:MM:SS.mmm")이다.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from src.common.types import Event


def parse_video_timestamp_seconds(value: Any) -> Optional[float]:
    """
    영상 timestamp를 초 단위로 변환한다.

    지원 형식:
    - "HH:MM:SS.mmm"
    - ISO 8601 문자열
    - int / float

    Args:
        value: timestamp 값

    Returns:
        초 단위 float. 변환 실패 시 None
    """
    if value is None:
        return None

    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip()

    try:
        parts = text.split(":")

        if len(parts) == 3:
            hours = int(parts[0])
            minutes = int(parts[1])
            seconds = float(parts[2])

            return hours * 3600 + minutes * 60 + seconds
    except ValueError:
        pass

    try:
        iso_text = text.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(iso_text)

        return parsed.timestamp()
    except ValueError:
        return None


def frame_to_seconds(frame_number: int, fps: float = 30.0) -> float:
    """
    frame_number를 영상 시간 초 단위로 변환한다.
    """
    if fps <= 0:
        fps = 30.0

    return max(frame_number, 0) / fps


def get_event_seconds(event: Event | Dict[str, Any], fps: float = 30.0) -> float:
    """
    이벤트의 영상 시각을 초 단위로 반환한다.

    timestamp가 우선이며, 변환 실패 시 frame_number / fps를 사용한다.
    """
    data = event if isinstance(event, dict) else event.__dict__

    timestamp_sec = parse_video_timestamp_seconds(data.get("timestamp"))

    if timestamp_sec is not None:
        return timestamp_sec

    frame_number = int(data.get("frame_number", 0) or 0)

    return frame_to_seconds(frame_number, fps=fps)


def event_sort_key(event: Event | Dict[str, Any], fps: float = 30.0) -> tuple:
    """
    이벤트 정렬 key를 생성한다.
    """
    data = event if isinstance(event, dict) else event.__dict__

    return (
        get_event_seconds(data, fps=fps),
        int(data.get("frame_number", 0) or 0),
        str(data.get("event_id", "")),
    )


def filter_events_by_video_time(
    events: List[Event | Dict[str, Any]],
    start_sec: float,
    end_sec: float,
    fps: float = 30.0,
) -> List[Event | Dict[str, Any]]:
    """
    영상 시간 기준으로 이벤트를 필터링한다.

    Args:
        events: Event 목록
        start_sec: 시작 시간(초)
        end_sec: 종료 시간(초)
        fps: 영상 FPS

    Returns:
        start_sec 이상 end_sec 이하에 해당하는 이벤트 목록
    """
    if start_sec > end_sec:
        start_sec, end_sec = end_sec, start_sec

    filtered: List[Event | Dict[str, Any]] = []

    for event in events:
        event_sec = get_event_seconds(event, fps=fps)

        if start_sec <= event_sec <= end_sec:
            filtered.append(event)

    return filtered