import src.common.event_aggregator as aggregator
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


def sample_events():
    return [
        make_event("e1", "00:00:01.000", "ENTER", 1, "zone_a", 30),
        make_event("e2", "00:00:04.000", "DWELL", 1, "zone_a", 120),
        make_event("e3", "00:00:06.000", "EXIT", 1, "zone_a", 180),
    ]


def test_event_aggregator_exports_expected_functions():
    expected_names = [
        "load_events_from_jsonl",
        "events_to_dataframe",
        "save_events_to_csv",
        "get_summary_kpi",
        "save_summary_json",
        "calculate_summary_kpi",
        "get_recent_events",
        "count_events_by_zone",
        "count_events_by_type",
        "events_per_time_bucket",
        "dwell_duration_distribution",
        "filter_events_by_video_time",
        "filter_events_by_period",
        "get_track_summary",
        "time_per_zone_by_track",
        "activity_intensity_by_time_bucket",
        "activity_intensity_by_hour",
        "get_track_ids_in_video_time",
        "get_track_ids_in_period",
        "generate_insights",
    ]

    for name in expected_names:
        assert hasattr(aggregator, name)


def test_event_aggregator_basic_calls():
    events = sample_events()

    summary = aggregator.calculate_summary_kpi(events)
    recent_events = aggregator.get_recent_events(events, n=2)
    zone_counts = aggregator.count_events_by_zone(events)
    type_counts = aggregator.count_events_by_type(events)
    time_df = aggregator.events_per_time_bucket(events, bucket_sec=5)
    dwell_df = aggregator.dwell_duration_distribution(events)
    track_summary = aggregator.get_track_summary(events, track_id=1)
    zone_times = aggregator.time_per_zone_by_track(events, track_id=1)
    activity_df = aggregator.activity_intensity_by_time_bucket(
        events,
        track_id=1,
        bucket_sec=5,
    )
    track_ids = aggregator.get_track_ids_in_video_time(
        events,
        start_sec=0,
        end_sec=10,
    )
    insights = aggregator.generate_insights(events)

    assert summary["total_events"] == 3
    assert len(recent_events) == 2
    assert zone_counts["zone_a"] == 3
    assert type_counts["ENTER"] == 1
    assert not time_df.empty
    assert not dwell_df.empty
    assert track_summary["total_events"] == 3
    assert zone_times["zone_a"] == 5.0
    assert not activity_df.empty
    assert track_ids == [1]
    assert insights


def test_event_aggregator_aliases_are_callable():
    events = sample_events()

    filtered = aggregator.filter_events_by_period(events, start_sec=0, end_sec=10)
    activity_df = aggregator.activity_intensity_by_hour(
        events,
        track_id=1,
        bucket_sec=5,
    )
    track_ids = aggregator.get_track_ids_in_period(
        events,
        start_sec=0,
        end_sec=10,
    )

    assert len(filtered) == 3
    assert not activity_df.empty
    assert track_ids == [1]
