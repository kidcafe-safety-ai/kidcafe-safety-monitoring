"""
track_id 기준 자녀 활동 리포트 차트 함수.

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
    from src.common.track_report import (
        activity_intensity_by_time_bucket,
        time_per_zone_by_track,
    )
except Exception:
    activity_intensity_by_time_bucket = None
    time_per_zone_by_track = None

try:
    from src.visualization.chart_style import configure_matplotlib_korean_font
except Exception:
    def configure_matplotlib_korean_font() -> None:
        return None

try:
    from src.visualization.event_charts import _empty_figure
except Exception:
    def _empty_figure(message: str) -> Figure:
        fig, ax = plt.subplots(figsize=(8, 4))
        ax.text(0.5, 0.5, message, ha="center", va="center", fontsize=12)
        ax.set_axis_off()
        fig.tight_layout()
        return fig


def _event_get(event: Any, key: str, default: Any = None) -> Any:
    if isinstance(event, dict):
        return event.get(key, default)
    return getattr(event, key, default)


def _base_style(fig: Figure, ax) -> None:
    fig.patch.set_facecolor("#141b2d")
    ax.set_facecolor("#0b1120")
    ax.tick_params(colors="#8896a8", labelsize=9)

    for spine in ax.spines.values():
        spine.set_color("#1e2d45")

    ax.title.set_color("#e2e8f0")
    ax.xaxis.label.set_color("#8896a8")
    ax.yaxis.label.set_color("#8896a8")


def _filter_track_events(events: List[Any], track_id: int) -> List[Any]:
    return [
        event for event in events
        if _event_get(event, "track_id") == track_id
    ]


def _fallback_zone_times(events: List[Any], track_id: int, fps: float = 30.0) -> Dict[str, float]:
    track_events = _filter_track_events(events, track_id)
    zone_counts: Counter[str] = Counter()

    for event in track_events:
        zone_id = _event_get(event, "zone_id")
        if zone_id:
            zone_counts[str(zone_id)] += 1

    # 정확한 체류 시간이 없으면 이벤트 수를 bucket 시간처럼 보수적으로 환산한다.
    return {zone_id: count * max(1.0, 1.0 / fps) for zone_id, count in zone_counts.items()}


def _fallback_activity_buckets(
    events: List[Any],
    track_id: int,
    bucket_sec: int = 10,
    fps: float = 30.0,
) -> pd.DataFrame:
    buckets: Dict[int, int] = defaultdict(int)

    for event in _filter_track_events(events, track_id):
        frame_number = _event_get(event, "frame_number", 0) or 0
        seconds = float(frame_number) / fps if fps else 0.0
        bucket = int(seconds // bucket_sec) * bucket_sec
        buckets[bucket] += 1

    if not buckets:
        return pd.DataFrame(columns=["bucket_start_sec", "event_count"])

    return pd.DataFrame(
        {
            "bucket_start_sec": sorted(buckets.keys()),
            "event_count": [buckets[key] for key in sorted(buckets.keys())],
        }
    )


def _extract_point(event: Any):
    foot_point = _event_get(event, "foot_point")

    if foot_point and len(foot_point) == 2:
        return float(foot_point[0]), float(foot_point[1])

    bbox = _event_get(event, "bbox")

    if bbox and len(bbox) >= 4:
        x1, y1, x2, y2 = [float(v) for v in bbox[:4]]
        return (x1 + x2) / 2, y2

    return None


def make_zone_donut_chart(events: List[Any], track_id: int, fps: float = 30.0) -> Figure:
    """특정 track_id의 구역별 체류 시간 도넛 차트를 생성한다."""
    configure_matplotlib_korean_font()

    if time_per_zone_by_track is not None:
        try:
            zone_times = time_per_zone_by_track(events, track_id=track_id, fps=fps)
        except Exception:
            zone_times = _fallback_zone_times(events, track_id=track_id, fps=fps)
    else:
        zone_times = _fallback_zone_times(events, track_id=track_id, fps=fps)

    if not zone_times:
        return _empty_figure(f"track_id={track_id}의 구역별 체류 데이터가 없습니다.")

    labels = list(zone_times.keys())
    values = list(zone_times.values())

    fig, ax = plt.subplots(figsize=(6, 6))
    fig.patch.set_facecolor("#141b2d")
    ax.set_facecolor("#0b1120")

    colors = ["#00d2c8", "#0080ff", "#FFC107", "#F44336", "#9E9E9E"]

    wedges, _ = ax.pie(
        values,
        labels=labels,
        startangle=90,
        wedgeprops={"width": 0.4},
        colors=colors[: len(values)],
        textprops={"color": "#e2e8f0"},
    )

    ax.set_title(f"Time per Zone - Track {track_id}", color="#e2e8f0")
    ax.legend(
        wedges,
        labels,
        title="Zone",
        loc="center left",
        bbox_to_anchor=(1, 0.5),
        labelcolor="#e2e8f0",
        framealpha=0,
    )

    fig.tight_layout()
    return fig


def make_activity_heatmap(
    events: List[Any],
    track_id: int,
    bucket_sec: int = 10,
    fps: float = 30.0,
) -> Figure:
    """특정 track_id의 시간 구간별 활동 강도 히트맵을 생성한다."""
    configure_matplotlib_korean_font()

    if activity_intensity_by_time_bucket is not None:
        try:
            df = activity_intensity_by_time_bucket(
                events,
                track_id=track_id,
                bucket_sec=bucket_sec,
                fps=fps,
            )
        except Exception:
            df = _fallback_activity_buckets(events, track_id=track_id, bucket_sec=bucket_sec, fps=fps)
    else:
        df = _fallback_activity_buckets(events, track_id=track_id, bucket_sec=bucket_sec, fps=fps)

    if df.empty:
        return _empty_figure(f"track_id={track_id}의 활동 데이터가 없습니다.")

    heatmap_values = [df["event_count"].tolist()]
    labels = df["bucket_start_sec"].astype(int).tolist()

    fig, ax = plt.subplots(figsize=(10, 2.5))
    _base_style(fig, ax)

    image = ax.imshow(heatmap_values, aspect="auto", cmap="magma")

    ax.set_title(f"Activity Intensity - Track {track_id}")
    ax.set_xlabel("Video Time Bucket Start (sec)")
    ax.set_yticks([])
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=45)

    colorbar = fig.colorbar(image, ax=ax, label="Event Count")
    colorbar.ax.yaxis.label.set_color("#8896a8")
    colorbar.ax.tick_params(colors="#8896a8")

    fig.tight_layout()
    return fig


def make_movement_heatmap(events: List[Any], track_id: int, width: int, height: int) -> Figure:
    """특정 track_id의 이동 경로 히트맵을 생성한다."""
    configure_matplotlib_korean_font()

    points = []

    for event in _filter_track_events(events, track_id):
        point = _extract_point(event)

        if point is None:
            continue

        points.append(point)

    if not points:
        return _empty_figure(f"track_id={track_id}의 이동 좌표 데이터가 없습니다.")

    xs = [point[0] for point in points]
    ys = [point[1] for point in points]

    fig, ax = plt.subplots(figsize=(8, 5))
    _base_style(fig, ax)

    heatmap = ax.hist2d(
        xs,
        ys,
        bins=30,
        range=[[0, width], [0, height]],
        cmap="magma",
    )

    ax.set_title(f"Movement Heatmap - Track {track_id}")
    ax.set_xlabel("X")
    ax.set_ylabel("Y")
    ax.invert_yaxis()

    colorbar = fig.colorbar(heatmap[3], ax=ax, label="Position Count")
    colorbar.ax.yaxis.label.set_color("#8896a8")
    colorbar.ax.tick_params(colors="#8896a8")

    fig.tight_layout()
    return fig