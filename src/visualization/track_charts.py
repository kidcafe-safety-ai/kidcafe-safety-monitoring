"""
track_id 기준 자녀 활동 리포트 차트 함수.

모든 함수는 Streamlit의 st.pyplot()에서 바로 사용할 수 있도록
matplotlib.figure.Figure 객체를 반환한다.
"""

from __future__ import annotations

from typing import Dict, List

import matplotlib.pyplot as plt
from matplotlib.figure import Figure

from src.common.track_report import (
    activity_intensity_by_time_bucket,
    time_per_zone_by_track,
)
from src.common.types import Event
from src.visualization.chart_style import configure_matplotlib_korean_font
from src.visualization.event_charts import _empty_figure


def make_zone_donut_chart(
    events: List[Event],
    track_id: int,
    fps: float = 30.0,
) -> Figure:
    """
    특정 track_id의 구역별 체류 시간 도넛 차트를 생성한다.
    """
    configure_matplotlib_korean_font()

    zone_times: Dict[str, float] = time_per_zone_by_track(
        events,
        track_id=track_id,
        fps=fps,
    )

    if not zone_times:
        return _empty_figure(f"track_id={track_id}의 구역별 체류 데이터가 없습니다.")

    labels = list(zone_times.keys())
    values = list(zone_times.values())

    fig, ax = plt.subplots(figsize=(6, 6))

    wedges, _ = ax.pie(
        values,
        labels=labels,
        startangle=90,
        wedgeprops={"width": 0.4},
    )

    ax.set_title(f"Time per Zone - Track {track_id}")
    ax.legend(
        wedges,
        labels,
        title="Zone",
        loc="center left",
        bbox_to_anchor=(1, 0.5),
    )

    fig.tight_layout()

    return fig


def make_activity_heatmap(
    events: List[Event],
    track_id: int,
    bucket_sec: int = 10,
    fps: float = 30.0,
) -> Figure:
    """
    특정 track_id의 시간 구간별 활동 강도 히트맵을 생성한다.
    """
    configure_matplotlib_korean_font()

    df = activity_intensity_by_time_bucket(
        events,
        track_id=track_id,
        bucket_sec=bucket_sec,
        fps=fps,
    )

    if df.empty:
        return _empty_figure(f"track_id={track_id}의 활동 데이터가 없습니다.")

    heatmap_values = [df["event_count"].tolist()]
    labels = df["bucket_start_sec"].astype(int).tolist()

    fig, ax = plt.subplots(figsize=(10, 2.5))

    image = ax.imshow(heatmap_values, aspect="auto")

    ax.set_title(f"Activity Intensity - Track {track_id}")
    ax.set_xlabel("Video Time Bucket Start (sec)")
    ax.set_yticks([])
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=45)

    fig.colorbar(image, ax=ax, label="Event Count")
    fig.tight_layout()

    return fig


def make_movement_heatmap(
    events: List[Event],
    track_id: int,
    width: int,
    height: int,
) -> Figure:
    """
    특정 track_id의 이동 경로 히트맵을 생성한다.
    """
    configure_matplotlib_korean_font()

    points = []

    for event in events:
        if event.track_id != track_id:
            continue

        if not event.foot_point or len(event.foot_point) != 2:
            continue

        x, y = event.foot_point
        points.append((float(x), float(y)))

    if not points:
        return _empty_figure(f"track_id={track_id}의 이동 좌표 데이터가 없습니다.")

    xs = [point[0] for point in points]
    ys = [point[1] for point in points]

    fig, ax = plt.subplots(figsize=(8, 5))

    heatmap = ax.hist2d(
        xs,
        ys,
        bins=30,
        range=[[0, width], [0, height]],
    )

    ax.set_title(f"Movement Heatmap - Track {track_id}")
    ax.set_xlabel("X")
    ax.set_ylabel("Y")
    ax.invert_yaxis()

    fig.colorbar(heatmap[3], ax=ax, label="Position Count")
    fig.tight_layout()

    return fig