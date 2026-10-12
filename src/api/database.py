"""SQLite connection and schema management for the API layer."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path


def get_project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def get_db_path() -> Path:
    env_path = os.getenv("KIDCAFE_DB_PATH")
    if env_path:
        return Path(env_path)
    return get_project_root() / "outputs" / "kidcafe_events.db"


def get_connection() -> sqlite3.Connection:
    """요청마다 새 SQLite connection을 연다.

    DB 파일이 없으면 schema를 다시 만든다. API 실행 중 DB 파일을 지우거나
    옮겨도(초기화·백업 교체) 재시작 없이 빈 DB로 다시 동작하게 하기 위해서다.
    이 처리가 없으면 sqlite3가 테이블 없는 빈 파일을 만들어 모든 요청이
    `no such table`로 500이 된다.
    """
    db_path = get_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    needs_schema = not db_path.exists()
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    if needs_schema:
        with connection:
            _create_schema(connection)
    return connection


# Phase 3에서 events 테이블에 추가되는 nullable 컬럼.
# 기존 DB에도 idempotent하게 적용된다 (_migrate_events_table 참고).
_EVENTS_PHASE_3_COLUMNS = {
    "event_confidence": "REAL",
    "cause_json": "TEXT",
}


def _migrate_events_table(connection: sqlite3.Connection) -> None:
    """기존 events 테이블에 Phase 3 nullable 컬럼을 추가한다.

    CREATE TABLE IF NOT EXISTS는 이미 테이블이 있으면 컬럼을 추가하지 않으므로,
    PRAGMA table_info로 컬럼 존재 여부를 확인한 뒤 없는 컬럼만 ALTER TABLE로 추가한다.
    여러 번 실행해도 안전하며, 기존 행은 두 컬럼 모두 NULL로 유지된다.
    참고: docs/api_contract.md SQLite Migration (Phase 3)
    """
    existing_columns = {
        row["name"] for row in connection.execute("PRAGMA table_info(events)")
    }
    for column, sql_type in _EVENTS_PHASE_3_COLUMNS.items():
        if column not in existing_columns:
            connection.execute(f"ALTER TABLE events ADD COLUMN {column} {sql_type}")


def init_db() -> None:
    with get_connection() as connection:
        _create_schema(connection)


def _create_schema(connection: sqlite3.Connection) -> None:
    """테이블·index·migration을 idempotent하게 적용한다."""
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS events (
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
    _migrate_events_table(connection)
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_events_event_type ON events(event_type)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_events_zone_id ON events(zone_id)"
    )
    connection.execute("CREATE INDEX IF NOT EXISTS idx_events_id ON events(id)")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS current_status (
            source TEXT PRIMARY KEY,
            frame_number INTEGER NOT NULL,
            active_track_count INTEGER NOT NULL,
            zone_occupancy_json TEXT NOT NULL,
            updated_at TEXT
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_current_status_updated_at "
        "ON current_status(updated_at)"
    )
