"""SQLite repository functions for event API routes."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.api.database import get_connection
from src.api.schemas import CurrentStatusCreate, EventCreate, timestamp_to_seconds


class DuplicateEventError(Exception):
    """Raised when event_id already exists."""


def _row_to_event(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "event_id": row["event_id"],
        "timestamp": row["timestamp"],
        "event_type": row["event_type"],
        "track_id": row["track_id"],
        "zone_id": row["zone_id"],
        "zone_name": row["zone_name"],
        "bbox": json.loads(row["bbox_json"]),
        "foot_point": json.loads(row["foot_point_json"]),
        "frame_number": row["frame_number"],
        "video_time_sec": row["video_time_sec"],
        "confidence": row["confidence"],
        "video_source": row["video_source"],
        "created_at": row["created_at"],
    }


def _row_to_current_status(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "source": row["source"],
        "frame_number": row["frame_number"],
        "active_track_count": row["active_track_count"],
        "zone_occupancy": json.loads(row["zone_occupancy_json"]),
        "updated_at": row["updated_at"],
    }


def create_event(event: EventCreate) -> Dict[str, Any]:
    video_time_sec = timestamp_to_seconds(event.timestamp)
    try:
        with get_connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO events (
                    event_id,
                    event_type,
                    track_id,
                    zone_id,
                    zone_name,
                    frame_number,
                    video_time_sec,
                    timestamp,
                    bbox_json,
                    foot_point_json,
                    confidence,
                    video_source
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.event_type,
                    event.track_id,
                    event.zone_id,
                    event.zone_name,
                    event.frame_number,
                    video_time_sec,
                    event.timestamp,
                    json.dumps(event.bbox),
                    json.dumps(event.foot_point),
                    event.confidence,
                    event.video_source,
                ),
            )
            row = connection.execute(
                "SELECT * FROM events WHERE id = ?",
                (cursor.lastrowid,),
            ).fetchone()
    except sqlite3.IntegrityError as exc:
        raise DuplicateEventError from exc

    return _row_to_event(row)


def upsert_current_status(status: CurrentStatusCreate) -> Dict[str, Any]:
    updated_at = status.updated_at or datetime.now(timezone.utc).astimezone().isoformat()
    zone_occupancy = [zone.model_dump() for zone in status.zone_occupancy]

    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO current_status (
                source,
                frame_number,
                active_track_count,
                zone_occupancy_json,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(source) DO UPDATE SET
                frame_number = excluded.frame_number,
                active_track_count = excluded.active_track_count,
                zone_occupancy_json = excluded.zone_occupancy_json,
                updated_at = excluded.updated_at
            """,
            (
                status.source,
                status.frame_number,
                status.active_track_count,
                json.dumps(zone_occupancy, ensure_ascii=False),
                updated_at,
            ),
        )

    return {
        "source": status.source,
        "updated": True,
    }


def get_current_status() -> Dict[str, Any]:
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT *
            FROM current_status
            ORDER BY updated_at DESC, source ASC
            LIMIT 1
            """
        ).fetchone()

    if row is None:
        return {
            "source": "unknown",
            "frame_number": 0,
            "active_track_count": 0,
            "zone_occupancy": [],
            "updated_at": None,
        }

    return _row_to_current_status(row)


def list_events(
    *,
    limit: int,
    offset: int,
    event_type: Optional[str] = None,
    zone_id: Optional[str] = None,
) -> Dict[str, Any]:
    clauses: List[str] = []
    params: List[Any] = []
    if event_type is not None:
        clauses.append("event_type = ?")
        params.append(event_type)
    if zone_id is not None:
        clauses.append("zone_id = ?")
        params.append(zone_id)

    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    with get_connection() as connection:
        total = connection.execute(
            f"SELECT COUNT(*) AS count FROM events {where_sql}",
            params,
        ).fetchone()["count"]
        rows = connection.execute(
            f"SELECT * FROM events {where_sql} ORDER BY id DESC LIMIT ? OFFSET ?",
            [*params, limit, offset],
        ).fetchall()

    items = [_row_to_event(row) for row in rows]
    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
        "count": len(items),
    }


def recent_events(limit: int) -> List[Dict[str, Any]]:
    with get_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM events ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [_row_to_event(row) for row in rows]


def get_summary() -> Dict[str, Any]:
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT
                COUNT(*) AS total_events,
                SUM(CASE WHEN event_type = 'ENTER' THEN 1 ELSE 0 END) AS enter_count,
                SUM(CASE WHEN event_type = 'DWELL' THEN 1 ELSE 0 END) AS dwell_count,
                SUM(CASE WHEN event_type = 'EXIT' THEN 1 ELSE 0 END) AS exit_count,
                COUNT(DISTINCT track_id) AS total_tracks,
                COUNT(DISTINCT video_source) AS video_count
            FROM events
            """
        ).fetchone()

    return {
        "total_events": row["total_events"],
        "enter_count": row["enter_count"] or 0,
        "dwell_count": row["dwell_count"] or 0,
        "exit_count": row["exit_count"] or 0,
        "total_tracks": row["total_tracks"],
        "video_count": row["video_count"],
        "avg_dwell_seconds": 0.0,
    }
