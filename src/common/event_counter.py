"""
이벤트 집계 모듈.

담당 기능:
- KPI 계산
- 최근 이벤트 조회
- 이벤트 타입별 개수
- 구역별 개수
- 시간 버킷별 이벤트 수
"""

from __future__ import annotations

from typing import Any, Dict, List

import pandas as pd

from src.common.dwell_analyzer import dwell_duration_distribution
from src.common.event_io import event_to_dict
from src.common.event_time import event_sort_key, get_event_seconds
from src.common.types import Event


def calculate_summary_kpi(
    events: List[Event | Dict[str, Any]],
    fps: float = 30.0,
) -> Dict[str, Any]:
    """
    이벤트 목록에서 KPI summary를 계산한다.
    """
    event_dicts = [event_to_dict(event) for event in events]

    total_events = len(event_dicts)
    enter_count = sum(
        1 for event in event_dicts if event.get("event_type") in ("ENTER", "ENTER_RESTRICTED")
    )
    dwell_count = sum(
        1
        for event in event_dicts
        if event.get("event_type") in ("DWELL", "DANGER_ZONE_DWELL")
    )
    exit_count = sum(1 for event in event_dicts if event.get("event_type") == "EXIT")

    total_tracks = len(
        {
            event.get("track_id")
            for event in event_dicts
            if event.get("track_id") is not None
        }
    )

    video_count = len(
        {
            event.get("video_source")
            for event in event_dicts
            if event.get("video_source")
        }
    )

    dwell_df = dwell_duration_distribution(event_dicts, fps=fps)
    avg_dwell_seconds = 0.0

    if not dwell_df.empty:
        avg_dwell_seconds = round(float(dwell_df["duration_seconds"].mean()), 2)

    return {
        "total_events": total_events,
        "enter_count": enter_count,
        "dwell_count": dwell_count,
        "exit_count": exit_count,
        "total_tracks": total_tracks,
        "video_count": video_count,
        "avg_dwell_seconds": avg_dwell_seconds,
    }


def get_recent_events(
    events: List[Event | Dict[str, Any]],
    n: int = 10,
    fps: float = 30.0,
) -> List[Event | Dict[str, Any]]:
    """
    최근 이벤트 n개를 반환한다.
    """
    if n <= 0:
        return []

    return sorted(
        events,
        key=lambda event: event_sort_key(event, fps=fps),
        reverse=True,
    )[:n]


def count_events_by_zone(events: List[Event | Dict[str, Any]]) -> Dict[str, int]:
    """
    zone_id별 이벤트 개수를 계산한다.
    """
    result: Dict[str, int] = {}

    for event in events:
        data = event_to_dict(event)
        zone_id = str(data.get("zone_id", "UNKNOWN"))

        result[zone_id] = result.get(zone_id, 0) + 1

    return result


def count_events_by_type(events: List[Event | Dict[str, Any]]) -> Dict[str, int]:
    """
    event_type별 이벤트 개수를 계산한다.
    """
    result: Dict[str, int] = {
        "ENTER": 0,
        "DWELL": 0,
        "EXIT": 0,
    }

    for event in events:
        data = event_to_dict(event)
        event_type = str(data.get("event_type", "UNKNOWN"))

        result[event_type] = result.get(event_type, 0) + 1

    return result


def events_per_time_bucket(
    events: List[Event | Dict[str, Any]],
    bucket_sec: int = 10,
    fps: float = 30.0,
) -> pd.DataFrame:
    """
    영상 시간 구간별 이벤트 개수를 계산한다.
    """
    if bucket_sec <= 0:
        raise ValueError("bucket_sec은 1 이상이어야 합니다.")

    rows = []

    for event in events:
        data = event_to_dict(event)
        video_sec = get_event_seconds(data, fps=fps)
        bucket_start = int(video_sec // bucket_sec) * bucket_sec

        rows.append(
            {
                "bucket_start_sec": bucket_start,
                "bucket_end_sec": bucket_start + bucket_sec,
                "event_type": data.get("event_type", "UNKNOWN"),
            }
        )

    columns = [
        "bucket_start_sec",
        "bucket_end_sec",
        "total",
        "ENTER",
        "DWELL",
        "EXIT",
    ]

    if not rows:
        return pd.DataFrame(columns=columns)

    df = pd.DataFrame(rows)

    pivot = (
        df.groupby(["bucket_start_sec", "bucket_end_sec", "event_type"])
        .size()
        .unstack(fill_value=0)
        .reset_index()
    )

    for event_type in ["ENTER", "DWELL", "EXIT"]:
        if event_type not in pivot.columns:
            pivot[event_type] = 0

    pivot["total"] = pivot[["ENTER", "DWELL", "EXIT"]].sum(axis=1)

    return pivot[columns].sort_values("bucket_start_sec").reset_index(drop=True)
