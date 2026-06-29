import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.api import repositories
from src.api.database import get_connection
from src.api.main import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    default_db_path = Path("outputs/kidcafe_events.db")
    default_db_exists = default_db_path.exists()
    db_path = tmp_path / "kidcafe_events_test.db"
    monkeypatch.setenv("KIDCAFE_DB_PATH", str(db_path))
    with TestClient(app) as test_client:
        yield test_client
    assert os.path.exists(db_path)
    assert default_db_path.exists() == default_db_exists


def make_event_payload(**overrides):
    payload = {
        "event_id": f"event-{uuid4()}",
        "timestamp": "00:00:10.600",
        "event_type": "ENTER",
        "track_id": 7,
        "zone_id": "playground_bottom_right",
        "bbox": [10.0, 20.0, 110.0, 220.0],
        "foot_point": [60.0, 220.0],
        "frame_number": 318,
        "video_source": "data/videos/test.mp4",
    }
    payload.update(overrides)
    return payload


def make_current_status_payload(**overrides):
    payload = {
        "source": "camera_01",
        "frame_number": 1230,
        "active_track_count": 4,
        "zone_occupancy": [
            {
                "zone_id": "playground_bottom_right",
                "zone_name": "test video zone",
                "current_count": 2,
                "risk_level": "HIGH",
            }
        ],
        "updated_at": "2026-06-08T10:15:30+09:00",
    }
    payload.update(overrides)
    return payload


def test_health_returns_common_response(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "success",
        "data": {
            "service": "kidcafe-api",
            "healthy": True,
        },
        "message": None,
    }


def test_post_events_stores_event_and_returns_created_event(client):
    payload = make_event_payload(zone_name="Test Zone", confidence=0.91)

    response = client.post("/events", json=payload)

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "success"
    assert body["message"] is None
    event = body["data"]
    assert event["id"] >= 1
    assert event["event_id"] == payload["event_id"]
    assert event["timestamp"] == "00:00:10.600"
    assert event["video_time_sec"] == 10.6
    assert event["event_type"] == "ENTER"
    assert event["zone_name"] == "Test Zone"
    assert event["confidence"] == 0.91
    assert event["bbox"] == payload["bbox"]
    assert event["foot_point"] == payload["foot_point"]
    assert event["created_at"]


def test_get_events_returns_paginated_latest_first_items(client):
    older = make_event_payload(event_type="ENTER", timestamp="00:00:01.000")
    newer = make_event_payload(event_type="DWELL", timestamp="00:00:02.000")
    newest_other_zone = make_event_payload(
        event_type="EXIT",
        timestamp="00:00:03.000",
        zone_id="other_zone",
    )

    for payload in [older, newer, newest_other_zone]:
        assert client.post("/events", json=payload).status_code == 201

    response = client.get(
        "/events",
        params={"limit": 1, "offset": 0, "event_type": "DWELL"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["message"] is None
    data = body["data"]
    assert data["total"] == 1
    assert data["limit"] == 1
    assert data["offset"] == 0
    assert data["count"] == 1
    assert data["items"][0]["event_id"] == newer["event_id"]

    all_response = client.get("/events")
    items = all_response.json()["data"]["items"]
    assert [item["event_id"] for item in items] == [
        newest_other_zone["event_id"],
        newer["event_id"],
        older["event_id"],
    ]


def test_get_events_total_is_after_filter_before_pagination(client):
    first = make_event_payload(event_type="ENTER", zone_id="zone-a")
    second = make_event_payload(event_type="ENTER", zone_id="zone-a")
    third = make_event_payload(event_type="ENTER", zone_id="zone-a")
    other = make_event_payload(event_type="EXIT", zone_id="zone-a")

    for payload in [first, second, third, other]:
        assert client.post("/events", json=payload).status_code == 201

    response = client.get(
        "/events",
        params={"event_type": "ENTER", "zone_id": "zone-a", "limit": 2},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["total"] == 3
    assert data["count"] == 2


def test_get_events_recent_returns_limited_latest_events(client):
    first = make_event_payload(timestamp="00:00:01.000")
    second = make_event_payload(timestamp="00:00:02.000")
    third = make_event_payload(timestamp="00:00:03.000")

    for payload in [first, second, third]:
        assert client.post("/events", json=payload).status_code == 201

    response = client.get("/events/recent", params={"limit": 2})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["message"] is None
    assert [item["event_id"] for item in body["data"]] == [
        third["event_id"],
        second["event_id"],
    ]


def test_get_events_recent_minutes_filters_created_at_boundaries(
    client,
    monkeypatch,
):
    monkeypatch.setattr(
        repositories,
        "_utc_now",
        lambda: datetime(2026, 6, 29, 3, 0, tzinfo=timezone.utc),
    )
    events_by_created_at = [
        (make_event_payload(timestamp="00:00:10.000"), "2026-06-29 02:49:59"),
        (make_event_payload(timestamp="23:59:59.999"), "2026-06-29 02:50:00"),
        (make_event_payload(timestamp="00:00:00.000"), "2026-06-29 03:00:00"),
        (make_event_payload(timestamp="00:00:00.000"), "2026-06-29 03:00:01"),
    ]

    for payload, _ in events_by_created_at:
        assert client.post("/events", json=payload).status_code == 201

    with get_connection() as connection:
        for payload, created_at in events_by_created_at:
            connection.execute(
                "UPDATE events SET created_at = ? WHERE event_id = ?",
                (created_at, payload["event_id"]),
            )

    response = client.get(
        "/events/recent",
        params={"minutes": 10, "limit": 5},
    )

    assert response.status_code == 200
    assert [item["event_id"] for item in response.json()["data"]] == [
        events_by_created_at[2][0]["event_id"],
        events_by_created_at[1][0]["event_id"],
    ]
    assert client.get("/summary").json()["data"]["recent_10min_event_count"] == 2


def test_recent_summary_count_is_not_limited_and_ties_are_deterministic(
    client,
    monkeypatch,
):
    monkeypatch.setattr(
        repositories,
        "_utc_now",
        lambda: datetime(2026, 6, 29, 3, 0, tzinfo=timezone.utc),
    )
    recent_payloads = [make_event_payload() for _ in range(7)]

    for payload in recent_payloads:
        assert client.post("/events", json=payload).status_code == 201

    with get_connection() as connection:
        connection.execute(
            "UPDATE events SET created_at = ?",
            ("2026-06-29 02:59:00",),
        )

    summary = client.get("/summary").json()["data"]
    recent = client.get(
        "/events/recent",
        params={"minutes": 10, "limit": 5},
    ).json()["data"]

    assert summary["recent_10min_event_count"] == 7
    assert len(recent) == 5
    assert [item["event_id"] for item in recent] == [
        payload["event_id"] for payload in reversed(recent_payloads[-5:])
    ]


@pytest.mark.parametrize("minutes", [0, 1441])
def test_get_events_recent_rejects_minutes_outside_range(client, minutes):
    response = client.get("/events/recent", params={"minutes": minutes})

    assert response.status_code == 422


def test_get_summary_returns_required_kpis(client, monkeypatch):
    monkeypatch.setattr(
        repositories,
        "_utc_now",
        lambda: datetime(2026, 6, 29, 3, 0, tzinfo=timezone.utc),
    )

    for payload in [
        make_event_payload(event_type="ENTER", track_id=1, video_source="a.mp4"),
        make_event_payload(event_type="DWELL", track_id=1, video_source="a.mp4"),
        make_event_payload(event_type="EXIT", track_id=2, video_source="b.mp4"),
    ]:
        assert client.post("/events", json=payload).status_code == 201

    with get_connection() as connection:
        connection.execute(
            "UPDATE events SET created_at = ?",
            ("2026-06-29 00:00:00",),
        )

    response = client.get("/summary")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data == {
        "total_events": 3,
        "today_event_count": 3,
        "recent_10min_event_count": 0,
        "enter_count": 1,
        "dwell_count": 1,
        "exit_count": 1,
        "total_tracks": 2,
        "video_count": 2,
        "avg_dwell_seconds": 0.0,
    }


def test_get_summary_counts_seoul_today_from_created_at_boundaries(
    client,
    monkeypatch,
):
    monkeypatch.setattr(
        repositories,
        "_utc_now",
        lambda: datetime(2026, 6, 29, 3, 0, tzinfo=timezone.utc),
    )
    events_by_created_at = [
        (make_event_payload(timestamp="23:59:59.999"), "2026-06-28 14:59:59"),
        (make_event_payload(timestamp="00:00:00.000"), "2026-06-28 15:00:00"),
        (make_event_payload(timestamp="00:00:00.000"), "2026-06-29 14:59:59"),
        (make_event_payload(timestamp="00:00:00.000"), "2026-06-29 15:00:00"),
    ]

    for payload, _ in events_by_created_at:
        assert client.post("/events", json=payload).status_code == 201

    with get_connection() as connection:
        for payload, created_at in events_by_created_at:
            connection.execute(
                "UPDATE events SET created_at = ? WHERE event_id = ?",
                (created_at, payload["event_id"]),
            )

    data = client.get("/summary").json()["data"]

    assert data["total_events"] == 4
    assert data["today_event_count"] == 2


def test_get_summary_returns_zero_when_seoul_today_has_no_events(
    client,
    monkeypatch,
):
    monkeypatch.setattr(
        repositories,
        "_utc_now",
        lambda: datetime(2026, 6, 29, 3, 0, tzinfo=timezone.utc),
    )
    payload = make_event_payload()
    assert client.post("/events", json=payload).status_code == 201

    with get_connection() as connection:
        connection.execute(
            "UPDATE events SET created_at = ? WHERE event_id = ?",
            ("2026-06-28 14:59:59", payload["event_id"]),
        )

    data = client.get("/summary").json()["data"]

    assert data["total_events"] == 1
    assert data["today_event_count"] == 0


def test_get_zones_returns_common_response(client):
    response = client.get("/zones")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["message"] is None
    assert isinstance(body["data"], list)
    assert body["data"]
    zone = body["data"][0]
    assert zone["zone_name"] == zone["name"]
    assert "rules" in zone


def test_get_status_current_returns_default_when_empty(client):
    response = client.get("/status/current")

    assert response.status_code == 200
    assert response.json() == {
        "status": "success",
        "data": {
            "source": "unknown",
            "frame_number": 0,
            "active_track_count": 0,
            "zone_occupancy": [],
            "updated_at": None,
        },
        "message": None,
    }


def test_put_status_current_stores_and_get_returns_latest_status(client):
    payload = make_current_status_payload()

    put_response = client.put("/status/current", json=payload)

    assert put_response.status_code == 200
    assert put_response.json() == {
        "status": "success",
        "data": {
            "source": "camera_01",
            "updated": True,
        },
        "message": None,
    }

    get_response = client.get("/status/current")

    assert get_response.status_code == 200
    body = get_response.json()
    assert body["status"] == "success"
    assert body["message"] is None
    assert body["data"] == payload


def test_put_status_current_generates_updated_at_when_missing(client):
    payload = make_current_status_payload()
    payload.pop("updated_at")

    response = client.put("/status/current", json=payload)

    assert response.status_code == 200
    data = client.get("/status/current").json()["data"]
    assert data["updated_at"]
    assert data["updated_at"] != "None"


def test_put_status_current_overwrites_same_source(client):
    first = make_current_status_payload(
        frame_number=1230,
        active_track_count=4,
        updated_at="2026-06-08T10:15:30+09:00",
    )
    second = make_current_status_payload(
        frame_number=1240,
        active_track_count=1,
        zone_occupancy=[
            {
                "zone_id": "playground_bottom_right",
                "zone_name": "test video zone",
                "current_count": 0,
                "risk_level": "NORMAL",
            }
        ],
        updated_at="2026-06-08T10:15:32+09:00",
    )

    assert client.put("/status/current", json=first).status_code == 200
    assert client.put("/status/current", json=second).status_code == 200

    data = client.get("/status/current").json()["data"]
    assert data == second


@pytest.mark.parametrize("risk_level", ["LOW", "MEDIUM"])
def test_put_status_current_rejects_unsupported_risk_level(client, risk_level):
    payload = make_current_status_payload(
        zone_occupancy=[
            {
                "zone_id": "playground_bottom_right",
                "zone_name": "test video zone",
                "current_count": 1,
                "risk_level": risk_level,
            }
        ]
    )

    response = client.put("/status/current", json=payload)

    assert response.status_code == 422


@pytest.mark.parametrize(
    "overrides",
    [
        {"frame_number": -1},
        {"active_track_count": -1},
        {
            "zone_occupancy": [
                {
                    "zone_id": "playground_bottom_right",
                    "zone_name": "test video zone",
                    "current_count": -1,
                    "risk_level": "HIGH",
                }
            ]
        },
    ],
)
def test_put_status_current_rejects_negative_counts(client, overrides):
    payload = make_current_status_payload(**overrides)

    response = client.put("/status/current", json=payload)

    assert response.status_code == 422


def test_invalid_event_type_returns_422(client):
    payload = make_event_payload(event_type="ALERT")

    response = client.post("/events", json=payload)

    assert response.status_code == 422


def test_invalid_timestamp_returns_422(client):
    payload = make_event_payload(timestamp="00:99:00.000")

    response = client.post("/events", json=payload)

    assert response.status_code == 422


def test_invalid_bbox_length_returns_422(client):
    payload = make_event_payload(bbox=[1.0, 2.0, 3.0])

    response = client.post("/events", json=payload)

    assert response.status_code == 422


def test_invalid_foot_point_length_returns_422(client):
    payload = make_event_payload(foot_point=[1.0])

    response = client.post("/events", json=payload)

    assert response.status_code == 422


def test_invalid_confidence_returns_422(client):
    payload = make_event_payload(confidence=1.1)

    response = client.post("/events", json=payload)

    assert response.status_code == 422


def test_duplicate_event_id_returns_409(client):
    payload = make_event_payload()
    assert client.post("/events", json=payload).status_code == 201

    response = client.post("/events", json=payload)

    assert response.status_code == 409
    assert response.json() == {
        "status": "error",
        "data": None,
        "message": "event_id already exists",
    }
