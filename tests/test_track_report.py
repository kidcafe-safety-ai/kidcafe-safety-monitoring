from src.common.track_report import (
    activity_intensity_by_time_bucket,
    get_track_ids_in_video_time,
    get_track_summary,
    time_per_zone_by_track,
)
from src.common.types import Event


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
        make_event("e1", "00:00:01.000", "ENTER", 1, "zone_a", 30, [0.0, 0.0]),
        make_event("e2", "00:00:04.000", "DWELL", 1, "zone_a", 120, [3.0, 4.0]),
        make_event("e3", "00:00:06.000", "EXIT", 1, "zone_a", 180, [6.0, 8.0]),
        make_event("e4", "00:00:08.000", "ENTER", 2, "zone_b", 240, [1.0, 1.0]),
    ]


def test_get_track_summary_normal_case():
    summary = get_track_summary(sample_events(), track_id=1)

    assert summary["track_id"] == 1
    assert summary["total_activity_seconds"] == 5.0
    assert summary["visited_zone_count"] == 1
    assert summary["visited_zones"] == ["zone_a"]
    assert summary["movement_distance"] == 10.0
    assert summary["risk_event_count"] == 2
    assert summary["total_events"] == 3


def test_get_track_summary_unknown_track_id():
    summary = get_track_summary(sample_events(), track_id=999)

    assert summary == {
        "track_id": 999,
        "total_activity_seconds": 0.0,
        "visited_zone_count": 0,
        "visited_zones": [],
        "movement_distance": 0.0,
        "risk_event_count": 0,
        "total_events": 0,
    }


def test_get_track_summary_empty_events():
    summary = get_track_summary([], track_id=1)

    assert summary["track_id"] == 1
    assert summary["total_events"] == 0
    assert summary["visited_zones"] == []


def test_time_per_zone_by_track():
    result = time_per_zone_by_track(sample_events(), track_id=1)

    assert result["zone_a"] == 5.0


def test_time_per_zone_by_track_unknown_track_id():
    result = time_per_zone_by_track(sample_events(), track_id=999)

    assert result == {}


def test_activity_intensity_by_time_bucket():
    df = activity_intensity_by_time_bucket(
        sample_events(),
        track_id=1,
        bucket_sec=5,
    )

    assert len(df) == 2
    assert df.loc[0, "bucket_start_sec"] == 0
    assert df.loc[0, "event_count"] == 2
    assert df.loc[1, "bucket_start_sec"] == 5
    assert df.loc[1, "event_count"] == 1


def test_activity_intensity_by_time_bucket_empty_events():
    df = activity_intensity_by_time_bucket([], track_id=1)

    assert df.empty
    assert list(df.columns) == ["bucket_start_sec", "bucket_end_sec", "event_count"]


def test_activity_intensity_by_time_bucket_invalid_bucket():
    try:
        activity_intensity_by_time_bucket(sample_events(), track_id=1, bucket_sec=0)
        assert False
    except ValueError as error:
        assert "bucket_sec" in str(error)


def test_get_track_ids_in_video_time():
    track_ids = get_track_ids_in_video_time(
        sample_events(),
        start_sec=0,
        end_sec=7,
    )

    assert track_ids == [1]


def test_get_track_ids_in_video_time_empty_events():
    track_ids = get_track_ids_in_video_time([], start_sec=0, end_sec=10)

    assert track_ids == []