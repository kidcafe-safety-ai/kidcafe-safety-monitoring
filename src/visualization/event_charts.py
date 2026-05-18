"""
이벤트/통계 대시보드용 matplotlib 차트 함수.

모든 함수는 Streamlit의 st.pyplot()에서 바로 사용할 수 있도록
matplotlib.figure.Figure 객체를 반환한다.
"""

from __future__ import annotations

from typing import Dict, List

import matplotlib.pyplot as plt
from matplotlib.figure import Figure

from src.common.dwell_analyzer import dwell_duration_distribution
from src.common.event_counter import (
    count_events_by_type,
    count_events_by_zone,
    events_per_time_bucket,
)
from src.common.event_time import get_event_seconds
from src.common.types import Event
from src.visualization.chart_style import configure_matplotlib_korean_font


EVENT_COLORS: Dict[str, str] = {
    "ENTER": "#FFC107",
    "DWELL": "#F44336",
    "EXIT": "#9E9E9E",
}


def _empty_figure(message: str) -> Figure:
    """
    데이터가 없을 때 사용할 빈 Figure를 생성한다.
    """
    configure_matplotlib_korean_font()

    fig, ax = plt.subplots(figsize=(8, 4))

    ax.text(
        0.5,
        0.5,
        message,
        ha="center",
        va="center",
        fontsize=12,
    )
    ax.set_axis_off()
    fig.tight_layout()

    return fig


def make_timeline_chart(
    events: List[Event],
    fps: float = 30.0,
) -> Figure:
    """
    영상 시간 기준 이벤트 타임라인 차트를 생성한다.
    """
    configure_matplotlib_korean_font()

    if not events:
        return _empty_figure("표시할 이벤트가 없습니다.")

    fig, ax = plt.subplots(figsize=(10, 4))

    event_types = ["ENTER", "DWELL", "EXIT"]

    for index, event_type in enumerate(event_types):
        subset = [event for event in events if event.event_type == event_type]

        if not subset:
            continue

        times = [get_event_seconds(event, fps=fps) for event in subset]

        ax.scatter(
            times,
            [index] * len(subset),
            label=event_type,
            color=EVENT_COLORS.get(event_type, "#999999"),
            s=60,
            alpha=0.85,
        )

    ax.set_title("Event Timeline")
    ax.set_xlabel("Video Time (sec)")
    ax.set_yticks(range(len(event_types)))
    ax.set_yticklabels(event_types)
    ax.grid(axis="x", linestyle="--", alpha=0.3)
    ax.legend()
    fig.tight_layout()

    return fig


def make_zone_bar_chart(events: List[Event]) -> Figure:
    """
    위험구역별 이벤트 발생 빈도 막대 차트를 생성한다.
    """
    configure_matplotlib_korean_font()

    zone_counts = count_events_by_zone(events)

    if not zone_counts:
        return _empty_figure("구역별 이벤트 데이터가 없습니다.")

    zones = list(zone_counts.keys())
    counts = list(zone_counts.values())

    fig, ax = plt.subplots(figsize=(8, 4))

    ax.bar(zones, counts)
    ax.set_title("Events by Zone")
    ax.set_xlabel("Zone")
    ax.set_ylabel("Event Count")
    ax.tick_params(axis="x", rotation=30)

    fig.tight_layout()

    return fig


def make_event_type_pie_chart(events: List[Event]) -> Figure:
    """
    이벤트 타입 비율 차트를 생성한다.
    """
    configure_matplotlib_korean_font()

    type_counts = count_events_by_type(events)

    if not type_counts or sum(type_counts.values()) == 0:
        return _empty_figure("이벤트 타입 데이터가 없습니다.")

    labels = list(type_counts.keys())
    values = list(type_counts.values())
    colors = [EVENT_COLORS.get(label, "#999999") for label in labels]

    fig, ax = plt.subplots(figsize=(6, 6))

    ax.pie(
        values,
        labels=labels,
        autopct="%1.1f%%",
        startangle=90,
        colors=colors,
    )
    ax.set_title("Event Type Ratio")

    fig.tight_layout()

    return fig


def make_hourly_line_chart(
    events: List[Event],
    bucket_sec: int = 10,
    fps: float = 30.0,
) -> Figure:
    """
    시간 구간별 이벤트 분포 라인 차트를 생성한다.

    역할 문서의 make_hourly_line_chart 이름을 유지하되,
    실제로는 영상 시간 bucket 기준으로 계산한다.
    """
    configure_matplotlib_korean_font()

    df = events_per_time_bucket(events, bucket_sec=bucket_sec, fps=fps)

    if df.empty:
        return _empty_figure("시간 구간별 이벤트 데이터가 없습니다.")

    fig, ax = plt.subplots(figsize=(10, 4))

    ax.plot(df["bucket_start_sec"], df["total"], marker="o", label="TOTAL")
    ax.plot(df["bucket_start_sec"], df["ENTER"], marker="o", label="ENTER")
    ax.plot(df["bucket_start_sec"], df["DWELL"], marker="o", label="DWELL")
    ax.plot(df["bucket_start_sec"], df["EXIT"], marker="o", label="EXIT")

    ax.set_title("Events per Time Bucket")
    ax.set_xlabel("Video Time Bucket Start (sec)")
    ax.set_ylabel("Event Count")
    ax.grid(axis="y", linestyle="--", alpha=0.3)
    ax.legend()

    fig.tight_layout()

    return fig


def make_time_bucket_chart(
    events: List[Event],
    bucket_sec: int = 10,
    fps: float = 30.0,
) -> Figure:
    """
    시간 구간별 이벤트 수 막대 차트를 생성한다.
    """
    configure_matplotlib_korean_font()

    df = events_per_time_bucket(events, bucket_sec=bucket_sec, fps=fps)

    if df.empty:
        return _empty_figure("시간 구간별 이벤트 데이터가 없습니다.")

    fig, ax = plt.subplots(figsize=(10, 4))

    ax.bar(df["bucket_start_sec"], df["total"], width=bucket_sec * 0.8)
    ax.set_title("Events per Time Bucket")
    ax.set_xlabel("Video Time (sec)")
    ax.set_ylabel("Event Count")
    ax.grid(axis="y", linestyle="--", alpha=0.3)

    fig.tight_layout()

    return fig


def make_dwell_histogram(
    events: List[Event],
    fps: float = 30.0,
) -> Figure:
    """
    체류 시간 히스토그램을 생성한다.
    """
    configure_matplotlib_korean_font()

    dwell_df = dwell_duration_distribution(events, fps=fps)

    if dwell_df.empty:
        return _empty_figure("체류 시간 데이터가 없습니다.")

    fig, ax = plt.subplots(figsize=(8, 4))

    ax.hist(dwell_df["duration_seconds"], bins=10)
    ax.set_title("Dwell Duration Distribution")
    ax.set_xlabel("Duration (sec)")
    ax.set_ylabel("Count")

    fig.tight_layout()

    return fig