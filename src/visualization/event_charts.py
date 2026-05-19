"""
이벤트/통계 대시보드용 matplotlib 차트 함수.

모든 함수는 Streamlit의 st.pyplot()에서 바로 사용할 수 있도록
matplotlib.figure.Figure 객체를 반환한다.
dict 이벤트와 Event 객체를 모두 지원한다.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Dict, List

import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.figure import Figure

try:
    from src.common.dwell_analyzer import dwell_duration_distribution
except Exception:
    dwell_duration_distribution = None

try:
    from src.common.event_counter import (
        count_events_by_type,
        count_events_by_zone,
        events_per_time_bucket,
    )
except Exception:
    count_events_by_type = None
    count_events_by_zone = None
    events_per_time_bucket = None

try:
    from src.common.event_time import get_event_seconds
except Exception:
    get_event_seconds = None

try:
    from src.visualization.chart_style import configure_matplotlib_korean_font
except Exception:
    def configure_matplotlib_korean_font() -> None:
        return None


EVENT_COLORS: Dict[str, str] = {
    "ENTER": "#FFC107",
    "DWELL": "#F44336",
    "EXIT": "#9E9E9E",
}


def _event_get(event: Any, key: str, default: Any = None) -> Any:
    if isinstance(event, dict):
        return event.get(key, default)
    return getattr(event, key, default)


def _event_seconds(event: Any, fps: float = 30.0) -> float:
    if get_event_seconds is not None:
        try:
            return float(get_event_seconds(event, fps=fps))
        except Exception:
            pass

    frame_number = _event_get(event, "frame_number", 0) or 0
    return float(frame_number) / fps if fps else 0.0


def _empty_figure(message: str) -> Figure:
    configure_matplotlib_korean_font()

    fig, ax = plt.subplots(figsize=(8, 4))
    ax.text(0.5, 0.5, message, ha="center", va="center", fontsize=12)
    ax.set_axis_off()
    fig.tight_layout()

    return fig


def _base_style(fig: Figure, ax) -> None:
    fig.patch.set_facecolor("#141b2d")
    ax.set_facecolor("#0b1120")
    ax.tick_params(colors="#8896a8", labelsize=9)

    for spine in ax.spines.values():
        spine.set_color("#1e2d45")

    ax.title.set_color("#e2e8f0")
    ax.xaxis.label.set_color("#8896a8")
    ax.yaxis.label.set_color("#8896a8")
    ax.grid(True, color="#1e2d45", linewidth=0.5, alpha=0.45)


def _fallback_count_by_zone(events: List[Any]) -> Dict[str, int]:
    counts: Dict[str, int] = defaultdict(int)

    for event in events:
        zone_id = _event_get(event, "zone_id")
        if zone_id:
            counts[str(zone_id)] += 1

    return dict(counts)


def _fallback_count_by_type(events: List[Any]) -> Dict[str, int]:
    return dict(Counter(_event_get(event, "event_type", "UNKNOWN") for event in events))


def _fallback_time_bucket(events: List[Any], bucket_sec: int = 10, fps: float = 30.0) -> pd.DataFrame:
    rows = []

    for event in events:
        event_type = _event_get(event, "event_type", "UNKNOWN")
        sec = _event_seconds(event, fps=fps)
        bucket = int(sec // bucket_sec) * bucket_sec

        rows.append(
            {
                "bucket_start_sec": bucket,
                "event_type": event_type,
            }
        )

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    pivot = (
        df.pivot_table(
            index="bucket_start_sec",
            columns="event_type",
            aggfunc="size",
            fill_value=0,
        )
        .reset_index()
        .sort_values("bucket_start_sec")
    )

    for event_type in ["ENTER", "DWELL", "EXIT"]:
        if event_type not in pivot.columns:
            pivot[event_type] = 0

    pivot["total"] = pivot[["ENTER", "DWELL", "EXIT"]].sum(axis=1)

    return pivot


def make_timeline_chart(events: List[Any], fps: float = 30.0) -> Figure:
    """영상 시간 기준 이벤트 타임라인 차트를 생성한다."""
    configure_matplotlib_korean_font()

    if not events:
        return _empty_figure("표시할 이벤트가 없습니다.")

    fig, ax = plt.subplots(figsize=(10, 4))
    _base_style(fig, ax)

    event_types = ["ENTER", "DWELL", "EXIT"]

    for index, event_type in enumerate(event_types):
        subset = [
            event for event in events
            if _event_get(event, "event_type") == event_type
        ]

        if not subset:
            continue

        times = [_event_seconds(event, fps=fps) for event in subset]

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
    ax.set_yticklabels(event_types, color="#e2e8f0")
    ax.legend(framealpha=0, labelcolor="#e2e8f0")
    fig.tight_layout()

    return fig


def make_zone_bar_chart(events: List[Any]) -> Figure:
    """위험구역별 이벤트 발생 빈도 막대 차트를 생성한다."""
    configure_matplotlib_korean_font()

    if count_events_by_zone is not None:
        try:
            zone_counts = count_events_by_zone(events)
        except Exception:
            zone_counts = _fallback_count_by_zone(events)
    else:
        zone_counts = _fallback_count_by_zone(events)

    if not zone_counts:
        return _empty_figure("구역별 이벤트 데이터가 없습니다.")

    zones = list(zone_counts.keys())
    counts = list(zone_counts.values())

    fig, ax = plt.subplots(figsize=(8, 4))
    _base_style(fig, ax)

    bars = ax.bar(zones, counts, color="#00d2c8", alpha=0.85)

    for bar, count in zip(bars, counts):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height(),
            str(count),
            ha="center",
            va="bottom",
            color="#e2e8f0",
            fontsize=9,
        )

    ax.set_title("Events by Zone")
    ax.set_xlabel("Zone")
    ax.set_ylabel("Event Count")
    ax.tick_params(axis="x", rotation=30)
    fig.tight_layout()

    return fig


def make_event_type_pie_chart(events: List[Any]) -> Figure:
    """이벤트 타입 비율 차트를 생성한다."""
    configure_matplotlib_korean_font()

    if count_events_by_type is not None:
        try:
            type_counts = count_events_by_type(events)
        except Exception:
            type_counts = _fallback_count_by_type(events)
    else:
        type_counts = _fallback_count_by_type(events)

    if not type_counts or sum(type_counts.values()) == 0:
        return _empty_figure("이벤트 타입 데이터가 없습니다.")

    labels = list(type_counts.keys())
    values = list(type_counts.values())
    colors = [EVENT_COLORS.get(label, "#999999") for label in labels]

    fig, ax = plt.subplots(figsize=(6, 6))
    fig.patch.set_facecolor("#141b2d")
    ax.set_facecolor("#0b1120")

    ax.pie(
        values,
        labels=labels,
        autopct="%1.1f%%",
        startangle=90,
        colors=colors,
        textprops={"color": "#e2e8f0"},
    )
    ax.set_title("Event Type Ratio", color="#e2e8f0")
    fig.tight_layout()

    return fig


def make_hourly_line_chart(events: List[Any], bucket_sec: int = 10, fps: float = 30.0) -> Figure:
    """
    시간 구간별 이벤트 분포 라인 차트를 생성한다.

    이름은 hourly지만 MVP에서는 영상 시간 bucket 기준으로 계산한다.
    """
    configure_matplotlib_korean_font()

    if events_per_time_bucket is not None:
        try:
            df = events_per_time_bucket(events, bucket_sec=bucket_sec, fps=fps)
        except Exception:
            df = _fallback_time_bucket(events, bucket_sec=bucket_sec, fps=fps)
    else:
        df = _fallback_time_bucket(events, bucket_sec=bucket_sec, fps=fps)

    if df.empty:
        return _empty_figure("시간 구간별 이벤트 데이터가 없습니다.")

    fig, ax = plt.subplots(figsize=(10, 4))
    _base_style(fig, ax)

    ax.plot(df["bucket_start_sec"], df["total"], marker="o", label="TOTAL", color="#00d2c8")
    ax.plot(df["bucket_start_sec"], df["ENTER"], marker="o", label="ENTER", color="#FFC107")
    ax.plot(df["bucket_start_sec"], df["DWELL"], marker="o", label="DWELL", color="#F44336")
    ax.plot(df["bucket_start_sec"], df["EXIT"], marker="o", label="EXIT", color="#9E9E9E")

    ax.set_title("Events per Time Bucket")
    ax.set_xlabel("Video Time Bucket Start (sec)")
    ax.set_ylabel("Event Count")
    ax.legend(framealpha=0, labelcolor="#e2e8f0")
    fig.tight_layout()

    return fig


def make_time_bucket_chart(events: List[Any], bucket_sec: int = 10, fps: float = 30.0) -> Figure:
    """시간 구간별 이벤트 수 막대 차트를 생성한다."""
    configure_matplotlib_korean_font()

    if events_per_time_bucket is not None:
        try:
            df = events_per_time_bucket(events, bucket_sec=bucket_sec, fps=fps)
        except Exception:
            df = _fallback_time_bucket(events, bucket_sec=bucket_sec, fps=fps)
    else:
        df = _fallback_time_bucket(events, bucket_sec=bucket_sec, fps=fps)

    if df.empty:
        return _empty_figure("시간 구간별 이벤트 데이터가 없습니다.")

    fig, ax = plt.subplots(figsize=(10, 4))
    _base_style(fig, ax)

    ax.bar(df["bucket_start_sec"], df["total"], width=bucket_sec * 0.8, color="#00d2c8", alpha=0.85)
    ax.set_title("Events per Time Bucket")
    ax.set_xlabel("Video Time (sec)")
    ax.set_ylabel("Event Count")
    fig.tight_layout()

    return fig


def make_dwell_histogram(events: List[Any], fps: float = 30.0) -> Figure:
    """체류 시간 히스토그램을 생성한다."""
    configure_matplotlib_korean_font()

    if dwell_duration_distribution is not None:
        try:
            dwell_df = dwell_duration_distribution(events, fps=fps)
        except Exception:
            dwell_df = pd.DataFrame()
    else:
        dwell_df = pd.DataFrame()

    if dwell_df.empty:
        dwell_events = [
            event for event in events
            if _event_get(event, "event_type") == "DWELL"
        ]
        durations = [
            _event_get(event, "duration_seconds", None)
            or _event_get(event, "dwell_seconds", None)
            for event in dwell_events
        ]
        durations = [float(value) for value in durations if value is not None]

        if durations:
            dwell_df = pd.DataFrame({"duration_seconds": durations})

    if dwell_df.empty:
        return _empty_figure("체류 시간 데이터가 없습니다.")

    fig, ax = plt.subplots(figsize=(8, 4))
    _base_style(fig, ax)

    ax.hist(dwell_df["duration_seconds"], bins=10, color="#F44336", alpha=0.8)
    ax.set_title("Dwell Duration Distribution")
    ax.set_xlabel("Duration (sec)")
    ax.set_ylabel("Count")
    fig.tight_layout()

    return fig