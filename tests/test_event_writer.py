import json

from src.common.event_io import load_events_from_jsonl
from src.common.event_writer import EventWriter
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


def test_event_writer_writes_jsonl_csv_and_summary(tmp_path):
    jsonl_path = tmp_path / "events.jsonl"
    csv_path = tmp_path / "events.csv"
    summary_path = tmp_path / "summary.json"

    writer = EventWriter(
        output_path=str(jsonl_path),
        csv_output_path=str(csv_path),
        summary_output_path=str(summary_path),
    )

    events = [
        make_event("e1", "00:00:01.000", "ENTER", 1, "zone_a", 30),
        make_event("e2", "00:00:06.000", "EXIT", 1, "zone_a", 180),
    ]

    writer.write_batch(events)
    writer.finalize(fps=30.0)

    assert jsonl_path.exists()
    assert csv_path.exists()
    assert summary_path.exists()

    loaded_events = load_events_from_jsonl(str(jsonl_path))

    assert len(loaded_events) == 2
    assert loaded_events[0].event_type == "ENTER"
    assert loaded_events[1].event_type == "EXIT"

    with open(summary_path, "r", encoding="utf-8") as file:
        summary = json.load(file)

    assert summary["total_events"] == 2
    assert summary["enter_count"] == 1
    assert summary["exit_count"] == 1
    assert summary["total_tracks"] == 1
    assert summary["video_count"] == 1
    assert summary["avg_dwell_seconds"] == 5.0


def test_event_writer_finalize_with_empty_events(tmp_path):
    jsonl_path = tmp_path / "events.jsonl"
    csv_path = tmp_path / "events.csv"
    summary_path = tmp_path / "summary.json"

    writer = EventWriter(
        output_path=str(jsonl_path),
        csv_output_path=str(csv_path),
        summary_output_path=str(summary_path),
    )

    writer.finalize(fps=30.0)

    assert jsonl_path.exists()
    assert csv_path.exists()
    assert summary_path.exists()

    with open(summary_path, "r", encoding="utf-8") as file:
        summary = json.load(file)

    assert summary["total_events"] == 0
    assert summary["enter_count"] == 0
    assert summary["dwell_count"] == 0
    assert summary["exit_count"] == 0
    assert summary["total_tracks"] == 0
    assert summary["video_count"] == 0
    assert summary["avg_dwell_seconds"] == 0.0