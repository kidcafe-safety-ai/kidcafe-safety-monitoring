"""
track_id 기준 자녀 활동 리포트 모듈.

담당 기능:
- 특정 track_id 활동 요약
- 구역별 체류 시간
- 시간 구간별 활동 강도
- 특정 구간 내 등장한 track_id 목록
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Sequence

import pandas as pd

from src.common.dwell_analyzer import dwell_duration_distribution, duration_seconds
from src.common.event_io import event_to_dict
from src.common.event_time import (
    event_sort_key,
    filter_events_by_video_time,
    get_event_seconds,
)
from src.common.types import Event


def _distance(p1: Sequence[float], p2: Sequence[float]) -> float:
    """
    두 좌표 사이의 유클리드 거리를 계산한다.
    """
    if len(p1) != 2 or len(p2) != 2:
        return 0.0

    return math.dist(
        [float(p1[0]), float(p1[1])],
        [float(p2[0]), float(p2[1])],
    )


def get_track_summary(
    events: List[Event | Dict[str, Any]],
    track_id: int,
    fps: float = 30.0,
) -> Dict[str, Any]:
    """
    특정 track_id의 활동 요약을 계산한다.

    Returns:
        {
            "track_id": int,
            "total_activity_seconds": float,
            "visited_zone_count": int,
            "visited_zones": List[str],
            "movement_distance": float,
            "risk_event_count": int,
            "total_events": int,
        }
    """
    track_events = [
        event_to_dict(event)
        for event in events
        if event_to_dict(event).get("track_id") == track_id
    ]

    track_events = sorted(
        track_events,
        key=lambda event: event_sort_key(event, fps=fps),
    )

    if not track_events:
        return {
            "track_id": track_id,
            "total_activity_seconds": 0.0,
            "visited_zone_count": 0,
            "visited_zones": [],
            "movement_distance": 0.0,
            "risk_event_count": 0,
            "total_events": 0,
        }

    first_event = track_events[0]
    last_event = track_events[-1]

    visited_zones = sorted(
        {
            event.get("zone_id")
            for event in track_events
            if event.get("zone_id") is not None
        }
    )

    movement_distance = 0.0
    previous_point = None

    for event in track_events:
        current_point = event.get("foot_point")

        if not current_point:
            continue

        if previous_point is not None:
            movement_distance += _distance(previous_point, current_point)

        previous_point = current_point

    risk_event_count = sum(
        1
        for event in track_events
        if event.get("event_type") in {"ENTER", "DWELL"}
    )

    return {
        "track_id": track_id,
        "total_activity_seconds": round(
            duration_seconds(first_event, last_event, fps=fps),
            2,
        ),
        "visited_zone_count": len(visited_zones),
        "visited_zones": visited_zones,
        "movement_distance": round(movement_distance, 2),
        "risk_event_count": risk_event_count,
        "total_events": len(track_events),
    }


def time_per_zone_by_track(
    events: List[Event | Dict[str, Any]],
    track_id: int,
    fps: float = 30.0,
) -> Dict[str, float]:
    """
    특정 track_id의 구역별 체류 시간을 계산한다.

    Returns:
        {
            "zone_id": duration_seconds
        }
    """
    track_events = [
        event
        for event in events
        if event_to_dict(event).get("track_id") == track_id
    ]

    dwell_df = dwell_duration_distribution(track_events, fps=fps)

    if dwell_df.empty:
        return {}

    grouped = dwell_df.groupby("zone_id")["duration_seconds"].sum()

    return {
        str(zone_id): round(float(duration), 2)
        for zone_id, duration in grouped.items()
    }


def activity_intensity_by_time_bucket(
    events: List[Event | Dict[str, Any]],
    track_id: int,
    bucket_sec: int = 10,
    fps: float = 30.0,
) -> pd.DataFrame:
    """
    특정 track_id의 시간 구간별 활동 강도를 계산한다.

    Returns:
        columns = ["bucket_start_sec", "bucket_end_sec", "event_count"]
    """
    if bucket_sec <= 0:
        raise ValueError("bucket_sec은 1 이상이어야 합니다.")

    rows = []

    for event in events:
        data = event_to_dict(event)

        if data.get("track_id") != track_id:
            continue

        video_sec = get_event_seconds(data, fps=fps)
        bucket_start = int(video_sec // bucket_sec) * bucket_sec

        rows.append(
            {
                "bucket_start_sec": bucket_start,
                "bucket_end_sec": bucket_start + bucket_sec,
                "event_count": 1,
            }
        )

    columns = ["bucket_start_sec", "bucket_end_sec", "event_count"]

    if not rows:
        return pd.DataFrame(columns=columns)

    df = pd.DataFrame(rows)

    return (
        df.groupby(["bucket_start_sec", "bucket_end_sec"], as_index=False)[
            "event_count"
        ]
        .sum()
        .sort_values("bucket_start_sec")
        .reset_index(drop=True)
    )


def get_track_ids_in_video_time(
    events: List[Event | Dict[str, Any]],
    start_sec: float,
    end_sec: float,
    fps: float = 30.0,
) -> List[int]:
    """
    특정 영상 시간 구간 안에 등장한 track_id 목록을 반환한다.
    """
    filtered_events = filter_events_by_video_time(
        events,
        start_sec=start_sec,
        end_sec=end_sec,
        fps=fps,
    )

    return sorted(
        {
            event_to_dict(event).get("track_id")
            for event in filtered_events
            if event_to_dict(event).get("track_id") is not None
        }
    )
