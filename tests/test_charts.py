import matplotlib

matplotlib.use("Agg")

from matplotlib.figure import Figure

from src.common.types import Event
from src.visualization.charts import (
    make_activity_heatmap,
    make_dwell_histogram,
    make_hourly_line_chart,
    make_movement_heatmap,
    make_timeline_chart,
    make_zone_bar_chart,
    make_zone_donut_chart,
)


def make_event(
    event_id: str,
    timestamp: str,
    event_type: str,
    track_id: int,
    zone_id: str,
    frame_number: int,
    foot_point=None,
) -> Event:
    return Event(
        event_id=event_id,
        timestamp=timestamp,
        event_type=event_type,
        track_id=track_id,
        zone_id=zone_id,
        bbox=[10.0, 20.0, 50.0, 100.0],
        foot_point=foot_point or [30.0, 100.0],
        frame_number=frame_number,
        video_source="test.mp4",
    )


def sample_events():
    return [
        make_event("e1", "00:00:01.000", "ENTER", 1, "zone_a", 30, [30.0, 100.0]),
        make_event("e2", "00:00:04.000", "DWELL", 1, "zone_a", 120, [45.0, 110.0]),
        make_event("e3", "00:00:06.000", "EXIT", 1, "zone_a", 180, [60.0, 120.0]),
    ]


def assert_is_figure(fig):
    assert isinstance(fig, Figure)


def test_make_timeline_chart_returns_figure():
    fig = make_timeline_chart(sample_events())
    assert_is_figure(fig)


def test_make_zone_bar_chart_returns_figure():
    fig = make_zone_bar_chart(sample_events())
    assert_is_figure(fig)


def test_make_hourly_line_chart_returns_figure():
    fig = make_hourly_line_chart(sample_events(), bucket_sec=5)
    assert_is_figure(fig)


def test_make_dwell_histogram_returns_figure():
    fig = make_dwell_histogram(sample_events())
    assert_is_figure(fig)


def test_make_zone_donut_chart_returns_figure():
    fig = make_zone_donut_chart(sample_events(), track_id=1)
    assert_is_figure(fig)


def test_make_activity_heatmap_returns_figure():
    fig = make_activity_heatmap(sample_events(), track_id=1)
    assert_is_figure(fig)


def test_make_movement_heatmap_returns_figure():
    fig = make_movement_heatmap(sample_events(), track_id=1, width=640, height=480)
    assert_is_figure(fig)


def test_chart_functions_handle_empty_events():
    fig = make_timeline_chart([])
    assert_is_figure(fig)