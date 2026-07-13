from src.common.insight_generator import generate_insights
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


def test_generate_insights_empty_events():
    insights = generate_insights([])

    assert insights == ["아직 분석할 이벤트가 없습니다."]


def test_generate_insights_top_zone():
    events = [
        make_event("e1", "00:00:01.000", "ENTER", 1, "zone_a", 30),
        make_event("e2", "00:00:02.000", "EXIT", 1, "zone_a", 60),
        make_event("e3", "00:00:03.000", "ENTER", 2, "zone_b", 90),
    ]

    insights = generate_insights(events)

    assert any("zone_a 구역에서 전체 이벤트의 66.7%" in item for item in insights)


def test_generate_insights_dwell_event_ratio():
    events = [
        make_event("e1", "00:00:01.000", "ENTER", 1, "zone_a", 30),
        make_event("e2", "00:00:02.000", "DWELL", 1, "zone_a", 60),
        make_event("e3", "00:00:03.000", "EXIT", 1, "zone_a", 90),
    ]

    insights = generate_insights(events)

    assert any("체류 위험(DWELL) 이벤트가 전체 이벤트의 33.3%" in item for item in insights)


def test_generate_insights_enter_more_than_exit():
    events = [
        make_event("e1", "00:00:01.000", "ENTER", 1, "zone_a", 30),
        make_event("e2", "00:00:02.000", "ENTER", 2, "zone_a", 60),
        make_event("e3", "00:00:03.000", "EXIT", 1, "zone_a", 90),
    ]

    insights = generate_insights(events)

    assert any("진입 이벤트가 이탈 이벤트보다 많아" in item for item in insights)


def test_generate_insights_total_tracks_over_threshold():
    events = [
        make_event("e1", "00:00:01.000", "ENTER", 1, "zone_a", 30),
        make_event("e2", "00:00:02.000", "ENTER", 2, "zone_a", 60),
        make_event("e3", "00:00:03.000", "ENTER", 3, "zone_a", 90),
        make_event("e4", "00:00:04.000", "ENTER", 4, "zone_a", 120),
        make_event("e5", "00:00:05.000", "ENTER", 5, "zone_a", 150),
    ]

    insights = generate_insights(events)

    assert any("총 5명의 추적 ID가 감지되어" in item for item in insights)


def test_generate_insights_default_message_when_no_special_pattern():
    events = [
        make_event("e1", "00:00:01.000", "EXIT", 1, "zone_a", 30),
    ]

    insights = generate_insights(events)

    assert insights
