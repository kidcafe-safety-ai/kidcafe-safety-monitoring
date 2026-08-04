"""SQLite repository functions for event API routes."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from src.api.database import get_connection
from src.api.schemas import CurrentStatusCreate, EventCreate, timestamp_to_seconds


class DuplicateEventError(Exception):
    """Raised when event_id already exists."""


SEOUL_TIMEZONE = ZoneInfo("Asia/Seoul")
SQLITE_TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"


def _utc_now() -> datetime:
    """Return an aware UTC time through a test-replaceable clock."""
    return datetime.now(timezone.utc)


def _sqlite_timestamp(value: datetime) -> str:
    """Format an aware datetime like SQLite CURRENT_TIMESTAMP."""
    return value.astimezone(timezone.utc).strftime(SQLITE_TIMESTAMP_FORMAT)


def _seoul_day_utc_bounds(now_utc: datetime) -> tuple[str, str]:
    """Return Seoul's current day boundaries in SQLite UTC text format."""
    seoul_today = now_utc.astimezone(SEOUL_TIMEZONE).date()
    start_seoul = datetime.combine(seoul_today, time.min, tzinfo=SEOUL_TIMEZONE)
    end_seoul = datetime.combine(
        seoul_today + timedelta(days=1),
        time.min,
        tzinfo=SEOUL_TIMEZONE,
    )
    return (
        _sqlite_timestamp(start_seoul),
        _sqlite_timestamp(end_seoul),
    )


def _sqlite_timestamp_ceil(value: datetime) -> str:
    """소수점 이하 초를 올려 저장 가능한 초 단위 시각으로 만든다.

    `created_at`은 초 단위로 저장되므로 소수점을 버리면 경계 의미가 뒤집힌다.
    `created_from=00:00:00.500`은 `00:00:00`에 저장된 이벤트를 제외해야 하고,
    `created_to=00:00:00.999`는 포함해야 한다. 양쪽 모두 올림하면 `created_from`
    포함·`created_to` 미포함 의미가 그대로 유지된다.
    """
    normalized = value.astimezone(timezone.utc)
    if normalized.microsecond:
        normalized = normalized.replace(microsecond=0) + timedelta(seconds=1)
    return _sqlite_timestamp(normalized)


def _recent_utc_bounds(now_utc: datetime, minutes: int) -> tuple[str, str]:
    """Return an inclusive recent window in SQLite UTC text format."""
    normalized_now = now_utc.astimezone(timezone.utc).replace(microsecond=0)
    return (
        _sqlite_timestamp(normalized_now - timedelta(minutes=minutes)),
        _sqlite_timestamp(normalized_now),
    )


def _row_to_event(row: sqlite3.Row) -> Dict[str, Any]:
    row_keys = row.keys()
    cause_json = row["cause_json"] if "cause_json" in row_keys else None
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
        "event_confidence": row["event_confidence"] if "event_confidence" in row_keys else None,
        "cause": json.loads(cause_json) if cause_json else None,
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
    cause_json = (
        json.dumps(event.cause.model_dump(), ensure_ascii=False)
        if event.cause is not None
        else None
    )
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
                    event_confidence,
                    cause_json,
                    video_source
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    event.event_confidence,
                    cause_json,
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
    updated_at = (
        status.updated_at or datetime.now(timezone.utc).astimezone().isoformat()
    )
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
    created_from: Optional[datetime] = None,
    created_to: Optional[datetime] = None,
) -> Dict[str, Any]:
    """이벤트 목록을 조회한다.

    `created_from`/`created_to`는 timezone을 포함한 datetime이며 UTC로 변환해
    SQLite `created_at`과 비교한다. 시작은 포함, 종료는 미포함이다. 영상 상대
    시각 `timestamp`는 기간 조회에 사용하지 않는다.

    `created_at`은 초 단위로 저장되므로 기간 입력의 소수점 이하 초는 다음 초로
    올려서 비교한다. 이렇게 해야 `created_from` 이상·`created_to` 미만 의미가
    유지된다 (`_sqlite_timestamp_ceil` 참고).

    `total`은 필터 적용 후, pagination 적용 전 전체 개수다.
    """
    clauses: List[str] = []
    params: List[Any] = []
    if event_type is not None:
        clauses.append("event_type = ?")
        params.append(event_type)
    if zone_id is not None:
        clauses.append("zone_id = ?")
        params.append(zone_id)
    if created_from is not None:
        clauses.append("created_at >= ?")
        params.append(_sqlite_timestamp_ceil(created_from))
    if created_to is not None:
        clauses.append("created_at < ?")
        params.append(_sqlite_timestamp_ceil(created_to))

    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    with get_connection() as connection:
        total = connection.execute(
            f"SELECT COUNT(*) AS count FROM events {where_sql}",
            params,
        ).fetchone()["count"]
        rows = connection.execute(
            f"SELECT * FROM events {where_sql} "
            f"ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
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


def recent_events(
    limit: int,
    minutes: Optional[int] = None,
) -> List[Dict[str, Any]]:
    with get_connection() as connection:
        if minutes is None:
            rows = connection.execute(
                "SELECT * FROM events ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        else:
            cutoff_utc, now_utc = _recent_utc_bounds(_utc_now(), minutes)
            rows = connection.execute(
                """
                SELECT *
                FROM events
                WHERE created_at >= ? AND created_at <= ?
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (cutoff_utc, now_utc, limit),
            ).fetchall()
    return [_row_to_event(row) for row in rows]


def get_summary() -> Dict[str, Any]:
    now_utc = _utc_now()
    today_start_utc, tomorrow_start_utc = _seoul_day_utc_bounds(now_utc)
    recent_cutoff_utc, recent_now_utc = _recent_utc_bounds(now_utc, 10)

    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT
                COUNT(*) AS total_events,
                SUM(
                    CASE
                        WHEN created_at >= ? AND created_at < ? THEN 1
                        ELSE 0
                    END
                ) AS today_event_count,
                SUM(
                    CASE
                        WHEN created_at >= ? AND created_at <= ? THEN 1
                        ELSE 0
                    END
                ) AS recent_10min_event_count,
                SUM(
                    CASE WHEN event_type IN ('ENTER', 'ENTER_RESTRICTED') THEN 1 ELSE 0 END
                ) AS enter_count,
                SUM(
                    CASE WHEN event_type IN ('DWELL', 'DANGER_ZONE_DWELL') THEN 1 ELSE 0 END
                ) AS dwell_count,
                SUM(CASE WHEN event_type = 'EXIT' THEN 1 ELSE 0 END) AS exit_count,
                COUNT(DISTINCT track_id) AS total_tracks,
                COUNT(DISTINCT video_source) AS video_count
            FROM events
            """,
            (
                today_start_utc,
                tomorrow_start_utc,
                recent_cutoff_utc,
                recent_now_utc,
            ),
        ).fetchone()

    return {
        "total_events": row["total_events"],
        "today_event_count": row["today_event_count"] or 0,
        "recent_10min_event_count": row["recent_10min_event_count"] or 0,
        "enter_count": row["enter_count"] or 0,
        "dwell_count": row["dwell_count"] or 0,
        "exit_count": row["exit_count"] or 0,
        "total_tracks": row["total_tracks"],
        "video_count": row["video_count"],
        "avg_dwell_seconds": 0.0,
    }
