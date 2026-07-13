"""Phase 3 SQLite migration (event_confidence, cause_json) 테스트."""

from __future__ import annotations

import sqlite3

import pytest

from src.api.database import init_db


def _create_legacy_events_table(db_path) -> None:
    """event_confidence/cause_json이 없는 Phase 2.5 스키마의 events 테이블을 만든다."""
    connection = sqlite3.connect(db_path)
    try:
        connection.execute(
            """
            CREATE TABLE events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL UNIQUE,
                event_type TEXT NOT NULL,
                track_id INTEGER NOT NULL,
                zone_id TEXT NOT NULL,
                zone_name TEXT,
                frame_number INTEGER NOT NULL,
                video_time_sec REAL,
                timestamp TEXT NOT NULL,
                bbox_json TEXT NOT NULL,
                foot_point_json TEXT NOT NULL,
                confidence REAL,
                video_source TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        connection.execute(
            """
            INSERT INTO events (
                event_id, event_type, track_id, zone_id, frame_number,
                timestamp, bbox_json, foot_point_json, video_source
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "legacy-1",
                "ENTER",
                1,
                "zone_a",
                0,
                "00:00:00.000",
                "[0,0,10,10]",
                "[5,10]",
                "test.mp4",
            ),
        )
        connection.commit()
    finally:
        connection.close()


def _table_columns(db_path) -> set:
    connection = sqlite3.connect(db_path)
    try:
        return {row[1] for row in connection.execute("PRAGMA table_info(events)")}
    finally:
        connection.close()


def test_migration_adds_columns_to_legacy_db(tmp_path, monkeypatch):
    db_path = tmp_path / "legacy.db"
    _create_legacy_events_table(db_path)
    assert "event_confidence" not in _table_columns(db_path)
    assert "cause_json" not in _table_columns(db_path)

    monkeypatch.setenv("KIDCAFE_DB_PATH", str(db_path))
    init_db()

    columns = _table_columns(db_path)
    assert "event_confidence" in columns
    assert "cause_json" in columns


def test_migration_preserves_existing_rows(tmp_path, monkeypatch):
    db_path = tmp_path / "legacy.db"
    _create_legacy_events_table(db_path)

    monkeypatch.setenv("KIDCAFE_DB_PATH", str(db_path))
    init_db()

    connection = sqlite3.connect(db_path)
    try:
        row = connection.execute(
            "SELECT event_id, event_confidence, cause_json FROM events WHERE event_id = ?",
            ("legacy-1",),
        ).fetchone()
    finally:
        connection.close()

    assert row is not None
    assert row[0] == "legacy-1"
    assert row[1] is None
    assert row[2] is None


def test_migration_is_idempotent(tmp_path, monkeypatch):
    db_path = tmp_path / "legacy.db"
    _create_legacy_events_table(db_path)
    monkeypatch.setenv("KIDCAFE_DB_PATH", str(db_path))

    init_db()
    init_db()
    init_db()

    columns = _table_columns(db_path)
    assert "event_confidence" in columns
    assert "cause_json" in columns


def test_init_db_on_fresh_db_already_has_phase_3_columns(tmp_path, monkeypatch):
    db_path = tmp_path / "fresh.db"
    monkeypatch.setenv("KIDCAFE_DB_PATH", str(db_path))

    init_db()

    columns = _table_columns(db_path)
    assert "event_confidence" in columns
    assert "cause_json" in columns


@pytest.mark.parametrize("call_count", [1, 2])
def test_init_db_does_not_raise(tmp_path, monkeypatch, call_count):
    db_path = tmp_path / "repeat.db"
    monkeypatch.setenv("KIDCAFE_DB_PATH", str(db_path))

    for _ in range(call_count):
        init_db()
