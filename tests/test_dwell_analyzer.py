from src.common.dwell_analyzer import dwell_duration_distribution, duration_seconds
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


def test_duration_seconds_uses_timestamp_first():
    start = {
        "timestamp": "00:00:01.000",
        "frame_number": 30,
    }
    end = {
        "timestamp": "00:00:06.500",
        "frame_number": 300,
    }

    result = duration_seconds(start, end, fps=30.0)

    assert result == 5.5


def test_dwell_duration_distribution_enter_to_exit():
    events = [
        make_event("e1", "00:00:01.000", "ENTER", 1, "zone_a", 30),
        make_event("e2", "00:00:06.000", "EXIT", 1, "zone_a", 180),
    ]

    df = dwell_duration_distribution(events)

    assert len(df) == 1
    assert df.loc[0, "track_id"] == 1
    assert df.loc[0, "zone_id"] == "zone_a"
    assert df.loc[0, "duration_seconds"] == 5.0


def test_dwell_duration_distribution_without_exit_uses_last_event():
    events = [
        make_event("e1", "00:00:01.000", "ENTER", 1, "zone_a", 30),
        make_event("e2", "00:00:04.000", "DWELL", 1, "zone_a", 120),
    ]

    df = dwell_duration_distribution(events)

    assert len(df) == 1
    assert df.loc[0, "duration_seconds"] == 3.0


def test_dwell_duration_distribution_empty_events():
    df = dwell_duration_distribution([])

    assert df.empty
    assert list(df.columns) == [
        "track_id",
        "zone_id",
        "start_frame",
        "end_frame",
        "duration_seconds",
    ]
