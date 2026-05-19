from src.common.event_counter import (
    calculate_summary_kpi,
    count_events_by_type,
    count_events_by_zone,
    events_per_time_bucket,
    get_recent_events,
)
from src.common.types import Event


def make_event(
    event_id: str,
    timestamp: str,
    event_type: str,
    track_id: int,
    zone_id: str,
    frame_number: int,
) -> Event:
    return Event(
        event_id=event_id,
        timestamp=timestamp,
        event_type=event_type,
        track_id=track_id,
        zone_id=zone_id,
        bbox=[10.0, 20.0, 50.0, 100.0],
        foot_point=[30.0, 100.0],
        frame_number=frame_number,
        video_source="test.mp4",
    )


def test_count_events_by_type():
    events = [
        make_event("e1", "00:00:01.000", "ENTER", 1, "zone_a", 30),
        make_event("e2", "00:00:02.000", "DWELL", 1, "zone_a", 60),
        make_event("e3", "00:00:03.000", "EXIT", 1, "zone_a", 90),
    ]

    result = count_events_by_type(events)

    assert result["ENTER"] == 1
    assert result["DWELL"] == 1
    assert result["EXIT"] == 1


def test_count_events_by_zone():
    events = [
        make_event("e1", "00:00:01.000", "ENTER", 1, "zone_a", 30),
        make_event("e2", "00:00:02.000", "DWELL", 1, "zone_a", 60),
        make_event("e3", "00:00:03.000", "ENTER", 2, "zone_b", 90),
    ]

    result = count_events_by_zone(events)

    assert result["zone_a"] == 2
    assert result["zone_b"] == 1


def test_calculate_summary_kpi():
    events = [
        make_event("e1", "00:00:01.000", "ENTER", 1, "zone_a", 30),
        make_event("e2", "00:00:06.000", "EXIT", 1, "zone_a", 180),
        make_event("e3", "00:00:03.000", "DWELL", 2, "zone_b", 90),
    ]

    summary = calculate_summary_kpi(events)

    assert summary["total_events"] == 3
    assert summary["enter_count"] == 1
    assert summary["dwell_count"] == 1
    assert summary["exit_count"] == 1
    assert summary["total_tracks"] == 2
    assert summary["video_count"] == 1
    assert summary["avg_dwell_seconds"] == 5.0


def test_get_recent_events():
    events = [
        make_event("e1", "00:00:01.000", "ENTER", 1, "zone_a", 30),
        make_event("e2", "00:00:03.000", "DWELL", 1, "zone_a", 90),
        make_event("e3", "00:00:02.000", "EXIT", 1, "zone_a", 60),
    ]

    recent = get_recent_events(events, n=2)

    assert len(recent) == 2
    assert recent[0].event_id == "e2"
    assert recent[1].event_id == "e3"


def test_events_per_time_bucket():
    events = [
        make_event("e1", "00:00:01.000", "ENTER", 1, "zone_a", 30),
        make_event("e2", "00:00:05.000", "DWELL", 1, "zone_a", 150),
        make_event("e3", "00:00:12.000", "EXIT", 1, "zone_a", 360),
    ]

    df = events_per_time_bucket(events, bucket_sec=10)

    assert len(df) == 2
    assert df.loc[0, "bucket_start_sec"] == 0
    assert df.loc[0, "total"] == 2
    assert df.loc[1, "bucket_start_sec"] == 10
    assert df.loc[1, "total"] == 1