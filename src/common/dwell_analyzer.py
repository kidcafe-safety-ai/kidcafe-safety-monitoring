"""
체류 시간 분석 모듈.

담당 기능:
- ENTER 이후 EXIT까지의 체류 시간 계산
- EXIT가 없는 경우 마지막 이벤트까지의 체류 시간 계산
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pandas as pd

from src.common.event_io import event_to_dict
from src.common.event_time import event_sort_key, parse_video_timestamp_seconds
from src.common.types import Event


def _duration_by_timestamp(
    first_event: Dict[str, Any],
    last_event: Dict[str, Any],
) -> Optional[float]:
    """
    두 이벤트의 timestamp 차이를 초 단위로 계산한다.
    """
    start_sec = parse_video_timestamp_seconds(first_event.get("timestamp"))
    end_sec = parse_video_timestamp_seconds(last_event.get("timestamp"))

    if start_sec is None or end_sec is None:
        return None

    return max(end_sec - start_sec, 0.0)


def _duration_by_frame(
    first_event: Dict[str, Any],
    last_event: Dict[str, Any],
    fps: float = 30.0,
) -> float:
    """
    두 이벤트의 frame_number 차이를 초 단위로 계산한다.
    """
    if fps <= 0:
        fps = 30.0

    start_frame = int(first_event.get("frame_number", 0) or 0)
    end_frame = int(last_event.get("frame_number", 0) or 0)

    return max((end_frame - start_frame) / fps, 0.0)


def duration_seconds(
    first_event: Dict[str, Any],
    last_event: Dict[str, Any],
    fps: float = 30.0,
) -> float:
    """
    두 이벤트 사이 시간을 초 단위로 계산한다.

    timestamp 계산이 가능하면 timestamp를 우선 사용하고,
    실패하면 frame_number / fps를 사용한다.
    """
    timestamp_duration = _duration_by_timestamp(first_event, last_event)

    if timestamp_duration is not None:
        return timestamp_duration

    return _duration_by_frame(first_event, last_event, fps=fps)


def dwell_duration_distribution(
    events: List[Event | Dict[str, Any]],
    fps: float = 30.0,
) -> pd.DataFrame:
    """
    체류 시간 분포를 계산한다.

    같은 track_id + zone_id 기준으로 ENTER 이후 EXIT까지 계산한다.
    EXIT가 없는 경우 마지막 이벤트까지의 시간을 사용한다.
    """
    event_dicts = sorted(
        [event_to_dict(event) for event in events],
        key=lambda event: event_sort_key(event, fps=fps),
    )

    open_sessions: Dict[tuple, Dict[str, Any]] = {}
    last_seen: Dict[tuple, Dict[str, Any]] = {}
    rows: List[Dict[str, Any]] = []

    for event in event_dicts:
        key = (event.get("track_id"), event.get("zone_id"))
        event_type = event.get("event_type")

        last_seen[key] = event

        if event_type == "ENTER":
            open_sessions[key] = event

        elif event_type == "EXIT":
            start_event = open_sessions.pop(key, None)

            if start_event is not None:
                rows.append(
                    {
                        "track_id": event.get("track_id"),
                        "zone_id": event.get("zone_id"),
                        "start_frame": start_event.get("frame_number"),
                        "end_frame": event.get("frame_number"),
                        "duration_seconds": round(
                            duration_seconds(start_event, event, fps=fps),
                            2,
                        ),
                    }
                )

    for key, start_event in open_sessions.items():
        last_event = last_seen.get(key, start_event)

        rows.append(
            {
                "track_id": start_event.get("track_id"),
                "zone_id": start_event.get("zone_id"),
                "start_frame": start_event.get("frame_number"),
                "end_frame": last_event.get("frame_number"),
                "duration_seconds": round(
                    duration_seconds(start_event, last_event, fps=fps),
                    2,
                ),
            }
        )

    return pd.DataFrame(
        rows,
        columns=[
            "track_id",
            "zone_id",
            "start_frame",
            "end_frame",
            "duration_seconds",
        ],
    )
