"""SQLite concurrent write regression tests for the Phase 3 API layer."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from src.api import repositories
from src.api.database import get_connection, init_db
from src.api.schemas import CurrentStatusCreate, EventCreate


def _make_fall_event(index: int) -> EventCreate:
    return EventCreate(
        event_id=f"concurrent-event-{index}",
        timestamp="00:00:10.600",
        event_type="FALL_SUSPECT",
        track_id=index,
        zone_id="__global__",
        bbox=[10.0, 20.0, 110.0, 220.0],
        foot_point=[60.0, 220.0],
        frame_number=300 + index,
        video_source="concurrency-test",
        event_confidence=0.82,
        cause={
            "type": "NEARBY_TRACK",
            "track_id": 1000 + index,
            "score": 0.68,
            "evidence": {
                "min_distance_norm": 0.31,
                "closing_speed_norm": 0.74,
                "time_to_fall_sec": 0.42,
            },
        },
    )


def _make_current_status(index: int) -> CurrentStatusCreate:
    return CurrentStatusCreate(
        source=f"camera-{index}",
        frame_number=100 + index,
        active_track_count=1,
        zone_occupancy=[
            {
                "zone_id": "danger-zone",
                "zone_name": "Danger Zone",
                "current_count": 1,
                "risk_level": "HIGH",
            }
        ],
        updated_at=f"2026-07-18T12:00:{index:02d}+09:00",
    )


def test_event_and_current_status_writes_are_safe_under_concurrency(
    tmp_path, monkeypatch
):
    db_path = tmp_path / "concurrent-writes.db"
    monkeypatch.setenv("KIDCAFE_DB_PATH", str(db_path))
    init_db()

    event_count = 24
    status_count = 8
    start_barrier = Barrier(event_count + status_count)

    def write_event(index: int):
        start_barrier.wait(timeout=10)
        return repositories.create_event(_make_fall_event(index))

    def write_status(index: int):
        start_barrier.wait(timeout=10)
        return repositories.upsert_current_status(_make_current_status(index))

    with ThreadPoolExecutor(max_workers=event_count + status_count) as executor:
        futures = [executor.submit(write_event, index) for index in range(event_count)]
        futures.extend(
            executor.submit(write_status, index) for index in range(status_count)
        )
        results = [future.result(timeout=20) for future in futures]

    assert len(results) == event_count + status_count

    with get_connection() as connection:
        event_rows = connection.execute(
            """
            SELECT event_id, event_confidence, cause_json
            FROM events
            ORDER BY event_id
            """
        ).fetchall()
        status_rows = connection.execute(
            "SELECT source FROM current_status ORDER BY source"
        ).fetchall()

    assert len(event_rows) == event_count
    assert len({row["event_id"] for row in event_rows}) == event_count
    assert all(row["event_confidence"] == 0.82 for row in event_rows)
    assert all(
        json.loads(row["cause_json"])["type"] == "NEARBY_TRACK"
        for row in event_rows
    )
    assert [row["source"] for row in status_rows] == [
        f"camera-{index}" for index in range(status_count)
    ]
