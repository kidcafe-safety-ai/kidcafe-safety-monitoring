"""GET /events 기간 필터 테스트 (Phase 4 Report 조회 계약).

계약: docs/api_contract.md `GET /events` Query Parameters·Phase 4 Report 사용
"""

import json
import os
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.api.database import get_connection
from src.api.main import app

INVALID_422_FIXTURE = "tests/fixtures/phase4_contract/validation_error_422.json"


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


def seed_events(client, specs):
    """`(created_at_utc, overrides)` 목록으로 이벤트를 만들고 event_id를 반환."""
    event_ids = []
    for created_at, overrides in specs:
        payload = make_event_payload(**overrides)
        assert client.post("/events", json=payload).status_code == 201
        event_ids.append(payload["event_id"])

    with get_connection() as connection:
        for (created_at, _), event_id in zip(specs, event_ids):
            connection.execute(
                "UPDATE events SET created_at = ? WHERE event_id = ?",
                (created_at, event_id),
            )

    return event_ids


@pytest.fixture()
def seeded(client):
    """2026-08-07 KST 하루를 사이에 두고 앞뒤로 걸친 이벤트."""
    # KST 2026-08-07 00:00 == UTC 2026-08-06 15:00
    return client, seed_events(
        client,
        [
            ("2026-08-06 14:59:59", {"event_type": "ENTER"}),          # 0 기간 이전
            ("2026-08-06 15:00:00", {"event_type": "ENTER"}),          # 1 시작 경계 (포함)
            ("2026-08-06 20:00:00", {"event_type": "FALL_SUSPECT",
                                     "zone_id": "__global__"}),        # 2 기간 내
            ("2026-08-07 14:59:59", {"event_type": "EXIT"}),           # 3 기간 내
            ("2026-08-07 15:00:00", {"event_type": "EXIT"}),           # 4 종료 경계 (미포함)
        ],
    )


def get_events(client, **params):
    response = client.get("/events", params=params)
    assert response.status_code == 200, response.text
    return response.json()["data"]


# ============ 하위 호환 ============


def test_existing_call_without_period_is_unchanged(seeded):
    client, event_ids = seeded

    data = get_events(client, limit=50)

    assert data["total"] == 5
    assert data["count"] == 5


def test_existing_filters_still_work(seeded):
    client, event_ids = seeded

    data = get_events(client, event_type="EXIT")

    assert data["total"] == 2
    assert {item["event_id"] for item in data["items"]} == {event_ids[3], event_ids[4]}


# ============ 기간 경계 ============


def test_created_from_is_inclusive(seeded):
    client, event_ids = seeded

    data = get_events(client, created_from="2026-08-07T00:00:00+09:00")

    returned = {item["event_id"] for item in data["items"]}
    assert event_ids[1] in returned
    assert event_ids[0] not in returned


def test_created_to_is_exclusive(seeded):
    client, event_ids = seeded

    data = get_events(client, created_to="2026-08-08T00:00:00+09:00")

    returned = {item["event_id"] for item in data["items"]}
    assert event_ids[3] in returned
    assert event_ids[4] not in returned


def test_full_day_range_selects_only_that_day(seeded):
    client, event_ids = seeded

    data = get_events(
        client,
        created_from="2026-08-07T00:00:00+09:00",
        created_to="2026-08-08T00:00:00+09:00",
    )

    assert data["total"] == 3
    assert {item["event_id"] for item in data["items"]} == {
        event_ids[1],
        event_ids[2],
        event_ids[3],
    }


def test_utc_input_matches_equivalent_kst_input(seeded):
    """timezone이 달라도 같은 순간이면 같은 결과여야 한다."""
    client, _ = seeded

    kst = get_events(
        client,
        created_from="2026-08-07T00:00:00+09:00",
        created_to="2026-08-08T00:00:00+09:00",
    )
    utc = get_events(
        client,
        created_from="2026-08-06T15:00:00Z",
        created_to="2026-08-07T15:00:00Z",
    )

    assert [i["event_id"] for i in kst["items"]] == [i["event_id"] for i in utc["items"]]


def test_empty_range_returns_empty_envelope(seeded):
    client, _ = seeded

    data = get_events(
        client,
        created_from="2026-09-01T00:00:00+09:00",
        created_to="2026-09-02T00:00:00+09:00",
    )

    assert data["items"] == []
    assert data["total"] == 0
    assert data["count"] == 0


def test_subsecond_input_is_truncated_to_seconds(client):
    """`created_at`이 초 단위 저장이라 소수점 이하 초는 버린다.

    `created_to=00:00:00.999`는 `00:00:00`으로 취급되며, 종료가 미포함이므로
    `00:00:00`에 저장된 이벤트는 빠진다. 그 초까지 포함하려면 다음 초를 준다.
    """
    seed_events(client, [("2026-08-06 15:00:00", {})])

    truncated = get_events(client, created_to="2026-08-07T00:00:00.999+09:00")
    next_second = get_events(client, created_to="2026-08-07T00:00:01+09:00")

    assert truncated["total"] == 0
    assert next_second["total"] == 1


def test_subsecond_created_from_includes_that_second(client):
    """`created_from`도 절삭되므로 해당 초에 저장된 이벤트가 포함된다."""
    seed_events(client, [("2026-08-06 15:00:00", {})])

    data = get_events(client, created_from="2026-08-07T00:00:00.500+09:00")

    assert data["total"] == 1


def test_video_timestamp_does_not_affect_period_filter(client):
    """영상 상대 시각 `timestamp`는 기간 조회에 사용하지 않는다."""
    event_ids = seed_events(
        client,
        [
            ("2026-08-06 20:00:00", {"timestamp": "23:59:59.999"}),
            ("2026-08-10 20:00:00", {"timestamp": "00:00:00.000"}),
        ],
    )

    data = get_events(
        client,
        created_from="2026-08-07T00:00:00+09:00",
        created_to="2026-08-08T00:00:00+09:00",
    )

    assert [item["event_id"] for item in data["items"]] == [event_ids[0]]


# ============ 다른 필터·pagination 조합 ============


def test_period_combines_with_event_type(seeded):
    client, event_ids = seeded

    data = get_events(
        client,
        created_from="2026-08-07T00:00:00+09:00",
        created_to="2026-08-08T00:00:00+09:00",
        event_type="FALL_SUSPECT",
    )

    assert [item["event_id"] for item in data["items"]] == [event_ids[2]]


def test_period_combines_with_zone_id(seeded):
    client, event_ids = seeded

    data = get_events(
        client,
        created_from="2026-08-07T00:00:00+09:00",
        created_to="2026-08-08T00:00:00+09:00",
        zone_id="__global__",
    )

    assert [item["event_id"] for item in data["items"]] == [event_ids[2]]


def test_total_is_filtered_count_before_pagination(seeded):
    """C가 total·offset으로 전체 페이지를 도는 계약의 전제다."""
    client, _ = seeded

    data = get_events(
        client,
        created_from="2026-08-07T00:00:00+09:00",
        created_to="2026-08-08T00:00:00+09:00",
        limit=2,
        offset=0,
    )

    assert data["total"] == 3
    assert data["count"] == 2
    assert data["limit"] == 2


def test_pagination_covers_range_without_overlap(seeded):
    client, _ = seeded
    period = {
        "created_from": "2026-08-07T00:00:00+09:00",
        "created_to": "2026-08-08T00:00:00+09:00",
    }

    first = get_events(client, limit=2, offset=0, **period)
    second = get_events(client, limit=2, offset=2, **period)

    collected = [i["event_id"] for i in first["items"]] + [
        i["event_id"] for i in second["items"]
    ]
    assert len(collected) == first["total"]
    assert len(set(collected)) == first["total"]


def test_results_are_newest_first(seeded):
    client, event_ids = seeded

    data = get_events(
        client,
        created_from="2026-08-07T00:00:00+09:00",
        created_to="2026-08-08T00:00:00+09:00",
    )

    assert [item["event_id"] for item in data["items"]] == [
        event_ids[3],
        event_ids[2],
        event_ids[1],
    ]


def test_same_created_at_falls_back_to_id_desc(client):
    event_ids = seed_events(
        client,
        [
            ("2026-08-06 20:00:00", {}),
            ("2026-08-06 20:00:00", {}),
            ("2026-08-06 20:00:00", {}),
        ],
    )

    data = get_events(client, created_from="2026-08-07T00:00:00+09:00")

    assert [item["event_id"] for item in data["items"]] == list(reversed(event_ids))


# ============ 422 검증 ============


def post_bad_range(client, **params):
    response = client.get("/events", params=params)
    assert response.status_code == 422, response.text
    return response.json()["detail"][0]


def test_naive_datetime_matches_frozen_422_fixture(client):
    with open(INVALID_422_FIXTURE, "r", encoding="utf-8") as f:
        expected = json.load(f)["detail"][0]

    detail = post_bad_range(client, created_from=expected["input"])

    assert detail["type"] == expected["type"]
    assert detail["loc"] == expected["loc"]
    assert detail["msg"] == expected["msg"]
    assert detail["input"] == expected["input"]


def test_naive_created_to_is_rejected(client):
    detail = post_bad_range(client, created_to="2026-08-08T00:00:00")

    assert detail["loc"] == ["query", "created_to"]
    assert detail["msg"] == "Value error, timezone is required"


def test_reversed_range_is_rejected(client):
    detail = post_bad_range(
        client,
        created_from="2026-08-08T00:00:00+09:00",
        created_to="2026-08-07T00:00:00+09:00",
    )

    assert detail["loc"] == ["query", "created_to"]
    assert "later than created_from" in detail["msg"]


def test_equal_range_is_rejected(client):
    """`created_from < created_to`여야 한다. 같은 값은 조회 구간이 비어 있다."""
    same = "2026-08-07T00:00:00+09:00"

    detail = post_bad_range(client, created_from=same, created_to=same)

    assert detail["loc"] == ["query", "created_to"]


@pytest.mark.parametrize("bad", ["nonsense", "2026-13-01T00:00:00+09:00", ""])
def test_malformed_datetime_is_rejected(client, bad):
    detail = post_bad_range(client, created_from=bad)

    assert detail["loc"] == ["query", "created_from"]


def test_range_check_runs_only_when_both_are_present(seeded):
    """한쪽만 주면 범위 검증 없이 통과해야 한다."""
    client, _ = seeded

    assert client.get(
        "/events", params={"created_to": "2026-08-07T00:00:00+09:00"}
    ).status_code == 200
    assert client.get(
        "/events", params={"created_from": "2026-08-08T00:00:00+09:00"}
    ).status_code == 200
