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
    db_path = get_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    return connection


def init_db() -> None:
    with get_connection() as connection:
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
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_events_event_type ON events(event_type)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_events_zone_id ON events(zone_id)"
        )
        connection.execute("CREATE INDEX IF NOT EXISTS idx_events_id ON events(id)")
