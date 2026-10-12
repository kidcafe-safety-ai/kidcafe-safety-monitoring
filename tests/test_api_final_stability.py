"""Final Phase Backend 회귀 테스트.

- 비유한 float(NaN·Infinity) 입력이 저장되어 조회 API 전체가 500이 되는 문제
- 필수 문자열 공백·음수 frame_number 입력
- CurrentStatus `updated_at` 검증과 offset이 다른 source 간 최신 판단
- 실행 종료 시 CurrentStatus 0명 초기화
- API 실행 중 DB 파일 삭제 후 재생성
- API 재시작 이후 Event·CurrentStatus 유지, LiveFrame 비움
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.api.live_frame_store import live_frame_store
from src.api.main import app


@pytest.fixture()
def db_path(tmp_path, monkeypatch):
    path = tmp_path / "kidcafe_final_stability.db"
    monkeypatch.setenv("KIDCAFE_DB_PATH", str(path))
    return path


@pytest.fixture()
def client(db_path):
    default_db_path = Path("outputs/kidcafe_events.db")
    default_db_exists = default_db_path.exists()
    live_frame_store.clear()
    with TestClient(app) as test_client:
        yield test_client
    live_frame_store.clear()
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


def make_status_payload(**overrides):
    payload = {
        "source": "camera_01",
        "frame_number": 10,
        "active_track_count": 2,
        "zone_occupancy": [
            {
                "zone_id": "playground_bottom_right",
                "zone_name": "놀이공간",
                "current_count": 2,
                "risk_level": "HIGH",
            }
        ],
        "updated_at": "2026-10-12T10:00:00+09:00",
    }
    payload.update(overrides)
    return payload


def post_raw_json(client, path, raw_body):
    """Python json이 허용하는 NaN·Infinity 리터럴을 그대로 보낸다."""
    return client.post(path, content=raw_body, headers={"content-type": "application/json"})


# --- 비유한 float 입력 ----------------------------------------------------


@pytest.mark.parametrize(
    "field, literal",
    [
        ("bbox", "[NaN, 20.0, 110.0, 220.0]"),
        ("bbox", "[10.0, Infinity, 110.0, 220.0]"),
        ("foot_point", "[60.0, -Infinity]"),
        ("confidence", "NaN"),
        ("event_confidence", "NaN"),
    ],
)
def test_non_finite_float_is_rejected_and_not_stored(client, field, literal):
    placeholder = "__NON_FINITE__"
    payload = make_event_payload(**{field: placeholder})
    raw = json.dumps(payload).replace(f'"{placeholder}"', literal)

    response = post_raw_json(client, "/events", raw)

    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)

    list_response = client.get("/events")
    assert list_response.status_code == 200
    assert list_response.json()["data"]["total"] == 0


def test_non_finite_cause_evidence_is_rejected(client):
    payload = make_event_payload(
        event_type="FALL_SUSPECT",
        zone_id="__global__",
        cause={
            "type": "NEARBY_TRACK",
            "track_id": 3,
            "score": 0.8,
            "evidence": {
                "min_distance_norm": 0.1,
                "closing_speed_norm": 0.2,
                "time_to_fall_sec": "__NON_FINITE__",
            },
        },
    )
    raw = json.dumps(payload).replace('"__NON_FINITE__"', "Infinity")

    response = post_raw_json(client, "/events", raw)

    assert response.status_code == 422
    assert client.get("/events").status_code == 200
    assert client.get("/events/recent").status_code == 200


@pytest.mark.parametrize(
    "overrides",
    [
        {"event_id": ""},
        {"zone_id": ""},
        {"video_source": ""},
        {"frame_number": -1},
    ],
)
def test_invalid_required_event_fields_return_422(client, overrides):
    response = client.post("/events", json=make_event_payload(**overrides))

    assert response.status_code == 422
    assert client.get("/events").json()["data"]["total"] == 0


def test_event_confidence_and_cause_round_trip_through_list_and_recent(client):
    cause = {
        "type": "NEARBY_TRACK",
        "track_id": 3,
        "score": 0.75,
        "evidence": {
            "min_distance_norm": 0.12,
            "closing_speed_norm": 0.4,
            "time_to_fall_sec": 0.8,
        },
    }
    payload = make_event_payload(
        event_type="FALL_SUSPECT",
        zone_id="__global__",
        event_confidence=0.66,
        cause=cause,
    )

    assert client.post("/events", json=payload).status_code == 201

    listed = client.get("/events").json()["data"]["items"][0]
    recent = client.get("/events/recent").json()["data"][0]
    for item in (listed, recent):
        assert item["event_id"] == payload["event_id"]
        assert item["event_confidence"] == pytest.approx(0.66)
        assert item["cause"] == cause


# --- CurrentStatus --------------------------------------------------------


@pytest.mark.parametrize(
    "updated_at",
    [
        "not-a-date",
        "2026-10-12T10:00:00",
        "2026-13-01T00:00:00+09:00",
        "",
        # Python fromisoformat()은 통과하지만 SQLite julianday()는 NULL인 값
        "2026-10-12T10:00:00+09:00:30",
        "2026-10-12X10:00:00+09:00",
        # SQLite는 읽지만 Python 3.10이 읽지 못하는 소수점 자릿수
        "2026-10-12T10:00:00.1+09:00",
        # 형식은 맞지만 존재하지 않는 날짜
        "2026-02-30T10:00:00+09:00",
        "2026-10-12T10:00:00+09:00\n",
    ],
)
def test_put_status_current_rejects_invalid_updated_at(client, updated_at):
    response = client.put(
        "/status/current", json=make_status_payload(updated_at=updated_at)
    )

    assert response.status_code == 422
    assert client.get("/status/current").json()["data"]["source"] == "unknown"


# PUT /status/current가 받는 형식. 모두 2026-10-12T01:00:00Z(UTC) 이후 시각이다.
VALID_UPDATED_AT = [
    "2026-10-12T01:00:00Z",
    "2026-10-12T01:00:00+00:00",
    "2026-10-12T10:00:00.123+09:00",
    "2026-10-12T10:00:00.123456+09:00",
    "2026-10-12 10:00:00+09:00",
    "2026-10-12T10:01+09:00",
    "2026-10-11T21:00:00-04:00",
]


@pytest.mark.parametrize("updated_at", VALID_UPDATED_AT)
def test_put_status_current_keeps_valid_updated_at_as_is(client, updated_at):
    assert (
        client.put(
            "/status/current", json=make_status_payload(updated_at=updated_at)
        ).status_code
        == 200
    )

    assert client.get("/status/current").json()["data"]["updated_at"] == updated_at


def test_get_status_current_compares_updated_at_across_offsets(client):
    # 문자열로는 "T10:00:00+09:00" > "T02:00:00Z"지만 실제로는 01:00Z < 02:00Z다.
    client.put(
        "/status/current",
        json=make_status_payload(source="older", updated_at="2026-10-12T10:00:00+09:00"),
    )
    client.put(
        "/status/current",
        json=make_status_payload(source="newer", updated_at="2026-10-12T02:00:00Z"),
    )

    assert client.get("/status/current").json()["data"]["source"] == "newer"


@pytest.mark.parametrize("updated_at", VALID_UPDATED_AT)
def test_accepted_updated_at_is_readable_by_sqlite_julianday(updated_at):
    """API가 받은 값은 GET 정렬에 쓰는 julianday()가 반드시 해석해야 한다."""
    connection = sqlite3.connect(":memory:")
    try:
        value = connection.execute("SELECT julianday(?)", (updated_at,)).fetchone()[0]
    finally:
        connection.close()

    assert value is not None


@pytest.mark.parametrize("newer_updated_at", VALID_UPDATED_AT)
def test_get_status_current_selects_newer_of_two_sources_for_each_format(
    client, newer_updated_at
):
    # older는 모든 VALID_UPDATED_AT보다 이른 시각이다(2026-10-12T00:59:59Z).
    client.put(
        "/status/current",
        json=make_status_payload(source="older", updated_at="2026-10-12T09:59:59+09:00"),
    )
    client.put(
        "/status/current",
        json=make_status_payload(
            source="newer",
            active_track_count=0,
            zone_occupancy=[],
            updated_at=newer_updated_at,
        ),
    )

    data = client.get("/status/current").json()["data"]
    assert data["source"] == "newer"
    assert data["active_track_count"] == 0
    assert data["updated_at"] == newer_updated_at


def test_status_reset_to_zero_on_shutdown_is_returned(client):
    client.put("/status/current", json=make_status_payload())
    reset = make_status_payload(
        frame_number=900,
        active_track_count=0,
        zone_occupancy=[
            {
                "zone_id": "playground_bottom_right",
                "zone_name": "놀이공간",
                "current_count": 0,
                "risk_level": "NORMAL",
            }
        ],
        updated_at="2026-10-12T10:05:00+09:00",
    )

    assert client.put("/status/current", json=reset).status_code == 200

    data = client.get("/status/current").json()["data"]
    assert data["active_track_count"] == 0
    assert data["frame_number"] == 900
    assert data["zone_occupancy"] == reset["zone_occupancy"]


def test_status_reset_of_new_source_replaces_previous_video_status(client):
    """playlist 전환: 이전 영상 source row가 남아 있어도 최신 source가 반환된다."""
    client.put(
        "/status/current",
        json=make_status_payload(source="video_a.mp4", updated_at="2026-10-12T10:00:00+09:00"),
    )
    client.put(
        "/status/current",
        json=make_status_payload(
            source="video_b.mp4",
            active_track_count=0,
            zone_occupancy=[],
            updated_at="2026-10-12T10:00:01+09:00",
        ),
    )

    data = client.get("/status/current").json()["data"]
    assert data["source"] == "video_b.mp4"
    assert data["active_track_count"] == 0


# --- DB 재생성 · API 재시작 -------------------------------------------------


def test_api_recreates_schema_when_db_file_is_deleted_while_running(client, db_path):
    assert client.post("/events", json=make_event_payload()).status_code == 201
    client.put("/status/current", json=make_status_payload())

    os.remove(db_path)

    events_response = client.get("/events")
    assert events_response.status_code == 200
    assert events_response.json()["data"]["total"] == 0
    assert client.get("/status/current").json()["data"]["source"] == "unknown"
    assert client.get("/summary").status_code == 200

    assert client.post("/events", json=make_event_payload()).status_code == 201
    assert client.get("/events").json()["data"]["total"] == 1


def test_api_recreates_db_when_outputs_directory_is_removed(tmp_path, monkeypatch):
    db_path = tmp_path / "outputs" / "kidcafe_events.db"
    monkeypatch.setenv("KIDCAFE_DB_PATH", str(db_path))
    with TestClient(app) as test_client:
        os.remove(db_path)
        os.rmdir(db_path.parent)

        assert test_client.post("/events", json=make_event_payload()).status_code == 201

    assert db_path.exists()


def test_restart_keeps_events_and_status_but_clears_live_frame(db_path):
    event = make_event_payload()
    jpeg = b"\xff\xd8\xff\xe0" + b"0" * 32 + b"\xff\xd9"

    with TestClient(app) as first:
        assert first.post("/events", json=event).status_code == 201
        assert first.put("/status/current", json=make_status_payload()).status_code == 200
        assert (
            first.put(
                "/live/frame",
                params={
                    "source": "camera_01",
                    "frame_number": 1,
                    "captured_at": "2026-10-12T01:00:00Z",
                },
                content=jpeg,
                headers={"content-type": "image/jpeg"},
            ).status_code
            == 200
        )

    # Live Frame은 process 메모리에만 있다. 프로세스 재시작을 흉내 낸다.
    live_frame_store.clear()

    with TestClient(app) as second:
        events = second.get("/events").json()["data"]
        assert events["total"] == 1
        assert events["items"][0]["event_id"] == event["event_id"]
        assert second.get("/status/current").json()["data"]["source"] == "camera_01"
        assert second.get("/live/frame").status_code == 204
        # 같은 event_id 재전송(Vision AI retry)은 중복 저장되지 않는다.
        assert second.post("/events", json=event).status_code == 409
        assert second.get("/events").json()["data"]["total"] == 1
