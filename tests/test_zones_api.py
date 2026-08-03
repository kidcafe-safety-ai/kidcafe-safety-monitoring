"""GET /zones · PUT /zones 계약 테스트 (Phase 4 Zone Settings).

계약: docs/api_contract.md `GET /zones Phase 4 계약`, `PUT /zones Phase 4 저장 계약`
"""

import json
import os
import re
import stat
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.api import zone_store
from src.api.main import app

FIXTURE_DIR = Path("tests/fixtures/phase4_contract")

VALID_ZONE = {
    "zone_id": "danger_door",
    "zone_name": "출입문 위험구역",
    "type": "polygon",
    "zone_type": "danger",
    "points": [[0.1, 0.2], [0.3, 0.2], [0.3, 0.5], [0.1, 0.5]],
    "rules": {"enter_alert": True, "dwell_threshold_sec": 5},
}


@pytest.fixture()
def runtime_path(tmp_path, monkeypatch):
    path = tmp_path / "zones_runtime.json"
    monkeypatch.setenv("KIDCAFE_ZONES_PATH", str(path))
    monkeypatch.setenv("KIDCAFE_DB_PATH", str(tmp_path / "test.db"))
    return path


@pytest.fixture()
def client(runtime_path):
    with TestClient(app) as test_client:
        yield test_client


def write_runtime(path: Path, zones):
    path.write_text(json.dumps(zones, ensure_ascii=False), encoding="utf-8")


def runtime_zone(**overrides):
    """내부 JSON 표현 (`zone_name`이 아니라 `name`)."""
    zone = {
        "zone_id": "danger_door",
        "name": "출입문 위험구역",
        "type": "polygon",
        "zone_type": "danger",
        "points": [[0.1, 0.2], [0.3, 0.2], [0.3, 0.5], [0.1, 0.5]],
        "rules": {"enter_alert": True, "dwell_threshold_sec": 5},
    }
    zone.update(overrides)
    return zone


def get_config(client):
    response = client.get("/zones")
    assert response.status_code == 200, response.text
    return response.json()["data"]


# ============ GET envelope ============


def test_get_returns_version_envelope(client, runtime_path):
    write_runtime(runtime_path, [runtime_zone()])

    data = get_config(client)

    assert set(data) == {"version", "updated_at", "zones"}
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", data["version"])
    assert data["updated_at"].endswith("Z")
    assert len(data["zones"]) == 1


def test_version_is_sha256_of_file_bytes(client, runtime_path):
    write_runtime(runtime_path, [runtime_zone()])

    data = get_config(client)

    assert data["version"] == zone_store.compute_version(runtime_path.read_bytes())


def test_internal_name_is_exposed_as_zone_name(client, runtime_path):
    write_runtime(runtime_path, [runtime_zone()])

    zone = get_config(client)["zones"][0]

    assert zone["zone_name"] == "출입문 위험구역"
    assert "name" not in zone


def test_valid_empty_file_succeeds(client, runtime_path):
    write_runtime(runtime_path, [])

    data = get_config(client)

    assert data["zones"] == []
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", data["version"])


def test_get_matches_success_fixture_shape(client, runtime_path):
    write_runtime(runtime_path, [runtime_zone()])
    with open(FIXTURE_DIR / "zones_get_success.json", "r", encoding="utf-8") as f:
        expected = json.load(f)

    body = client.get("/zones").json()

    assert body["status"] == expected["status"]
    assert body["message"] == expected["message"]
    assert set(body["data"]) == set(expected["data"])
    assert set(body["data"]["zones"][0]) == set(expected["data"]["zones"][0])


# ============ GET 오류는 500, 빈 배열로 대체 금지 ============


def unavailable_body():
    with open(FIXTURE_DIR / "zones_get_unavailable.json", "r", encoding="utf-8") as f:
        return json.load(f)


def test_missing_file_returns_500_not_empty_list(client, runtime_path):
    assert not runtime_path.exists()

    response = client.get("/zones")

    assert response.status_code == 500
    assert response.json() == unavailable_body()


def test_broken_json_returns_500(client, runtime_path):
    runtime_path.write_text("{not json", encoding="utf-8")

    response = client.get("/zones")

    assert response.status_code == 500
    assert response.json() == unavailable_body()


def test_non_array_payload_returns_500(client, runtime_path):
    runtime_path.write_text('{"zones": []}', encoding="utf-8")

    assert client.get("/zones").status_code == 500


@pytest.mark.parametrize("field", ["zone_id", "name", "type", "zone_type", "points"])
def test_missing_zone_field_returns_500(client, runtime_path, field):
    zone = runtime_zone()
    del zone[field]
    write_runtime(runtime_path, [zone])

    assert client.get("/zones").status_code == 500


def test_invalid_polygon_in_runtime_returns_500(client, runtime_path):
    write_runtime(
        runtime_path,
        [runtime_zone(points=[[0.1, 0.1], [0.3, 0.3], [0.1, 0.3], [0.3, 0.1]])],
    )

    assert client.get("/zones").status_code == 500


def test_duplicate_zone_id_in_runtime_returns_500(client, runtime_path):
    write_runtime(runtime_path, [runtime_zone(), runtime_zone()])

    assert client.get("/zones").status_code == 500


# ============ PUT 저장 ============


def seed_and_get_version(client, runtime_path):
    write_runtime(runtime_path, [runtime_zone()])
    return get_config(client)["version"]


def test_put_replaces_and_returns_same_envelope(client, runtime_path):
    version = seed_and_get_version(client, runtime_path)
    updated = {**VALID_ZONE, "rules": {"enter_alert": True, "dwell_threshold_sec": 7}}

    response = client.put(
        "/zones", json={"expected_version": version, "zones": [updated]}
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert set(data) == {"version", "updated_at", "zones"}
    assert data["zones"][0]["rules"]["dwell_threshold_sec"] == 7
    assert data["version"] != version


def test_saved_value_survives_refetch(client, runtime_path):
    version = seed_and_get_version(client, runtime_path)
    updated = {**VALID_ZONE, "zone_name": "새 이름"}

    client.put("/zones", json={"expected_version": version, "zones": [updated]})

    assert get_config(client)["zones"][0]["zone_name"] == "새 이름"


def test_put_writes_internal_name_for_vision_ai(client, runtime_path):
    """Vision AI의 zone_loader가 읽는 내부 형식은 `name`을 유지해야 한다."""
    version = seed_and_get_version(client, runtime_path)

    client.put("/zones", json={"expected_version": version, "zones": [VALID_ZONE]})

    saved = json.loads(runtime_path.read_text(encoding="utf-8"))
    assert "name" in saved[0]
    assert "zone_name" not in saved[0]


def test_omitted_zone_is_deleted(client, runtime_path):
    """일부 Zone만 보내면 누락한 Zone은 삭제 대상이다."""
    write_runtime(
        runtime_path,
        [runtime_zone(), runtime_zone(zone_id="play_area", name="놀이 구역", zone_type="play")],
    )
    version = get_config(client)["version"]

    response = client.put(
        "/zones", json={"expected_version": version, "zones": [VALID_ZONE]}
    )

    assert [zone["zone_id"] for zone in response.json()["data"]["zones"]] == ["danger_door"]


def test_empty_zone_list_can_be_saved(client, runtime_path):
    version = seed_and_get_version(client, runtime_path)

    response = client.put("/zones", json={"expected_version": version, "zones": []})

    assert response.status_code == 200
    assert response.json()["data"]["zones"] == []


def test_returned_version_is_usable_for_next_save(client, runtime_path):
    version = seed_and_get_version(client, runtime_path)

    first = client.put(
        "/zones", json={"expected_version": version, "zones": [VALID_ZONE]}
    )
    second = client.put(
        "/zones",
        json={
            "expected_version": first.json()["data"]["version"],
            "zones": [VALID_ZONE],
        },
    )

    assert second.status_code == 200


# ============ 409 version 충돌 ============


def test_stale_version_returns_409(client, runtime_path):
    version = seed_and_get_version(client, runtime_path)
    client.put("/zones", json={"expected_version": version, "zones": [VALID_ZONE]})

    response = client.put(
        "/zones", json={"expected_version": version, "zones": [VALID_ZONE]}
    )

    assert response.status_code == 409
    with open(FIXTURE_DIR / "zones_version_conflict.json", "r", encoding="utf-8") as f:
        assert response.json() == json.load(f)


def test_conflict_does_not_modify_file(client, runtime_path):
    version = seed_and_get_version(client, runtime_path)
    client.put("/zones", json={"expected_version": version, "zones": [VALID_ZONE]})
    before = runtime_path.read_bytes()

    client.put(
        "/zones",
        json={
            "expected_version": version,
            "zones": [{**VALID_ZONE, "zone_name": "덮어쓰면 안 됨"}],
        },
    )

    assert runtime_path.read_bytes() == before


# ============ 422 검증 ============


def put_invalid(client, runtime_path, zone_overrides=None, **request_overrides):
    version = seed_and_get_version(client, runtime_path)
    body = {
        "expected_version": version,
        "zones": [{**VALID_ZONE, **(zone_overrides or {})}],
    }
    body.update(request_overrides)
    response = client.put("/zones", json=body)
    assert response.status_code == 422, response.text
    return response.json()["detail"][0]


def test_self_intersecting_polygon_matches_frozen_fixture(client, runtime_path):
    with open(FIXTURE_DIR / "zones_invalid_polygon_422.json", "r", encoding="utf-8") as f:
        expected = json.load(f)["detail"][0]

    detail = put_invalid(client, runtime_path, {"points": expected["input"]})

    assert detail["type"] == expected["type"]
    assert detail["msg"] == expected["msg"]
    assert detail["loc"][-1] == "points"


@pytest.mark.parametrize(
    "points",
    [
        [[0.1, 0.2], [0.3, 0.2]],
        [[0.1, 0.2], [0.3, 0.2], [1.1, 0.5]],
        [[0.1, 0.2], [0.3, 0.2], [0.3, 0.5], [0.1, 0.2]],
        [[0.1, 0.2], [0.3, 0.2], [0.1, 0.2], [0.3, 0.5]],
        [[0.1, 0.1], [0.2, 0.2], [0.3, 0.3]],
    ],
    ids=["too_few", "out_of_range", "closed_ring", "duplicate", "zero_area"],
)
def test_invalid_polygon_shapes_rejected(client, runtime_path, points):
    put_invalid(client, runtime_path, {"points": points})


@pytest.mark.parametrize("dwell", [-1, 3601])
def test_dwell_threshold_out_of_range_rejected(client, runtime_path, dwell):
    put_invalid(
        client, runtime_path, {"rules": {"enter_alert": True, "dwell_threshold_sec": dwell}}
    )


@pytest.mark.parametrize("field,value", [("zone_id", ""), ("zone_name", "   ")])
def test_blank_identifier_rejected(client, runtime_path, field, value):
    put_invalid(client, runtime_path, {field: value})


def test_unknown_zone_type_rejected(client, runtime_path):
    put_invalid(client, runtime_path, {"zone_type": "playground"})


def test_non_polygon_type_rejected(client, runtime_path):
    put_invalid(client, runtime_path, {"type": "circle"})


def test_duplicate_zone_id_rejected(client, runtime_path):
    version = seed_and_get_version(client, runtime_path)

    response = client.put(
        "/zones",
        json={"expected_version": version, "zones": [VALID_ZONE, VALID_ZONE]},
    )

    assert response.status_code == 422


@pytest.mark.parametrize(
    "version", ["", "sha256:xyz", "deadbeef", "sha256:" + "A" * 64]
)
def test_malformed_expected_version_rejected(client, runtime_path, version):
    write_runtime(runtime_path, [runtime_zone()])

    response = client.put(
        "/zones", json={"expected_version": version, "zones": [VALID_ZONE]}
    )

    assert response.status_code == 422


def test_validation_failure_does_not_modify_file(client, runtime_path):
    version = seed_and_get_version(client, runtime_path)
    before = runtime_path.read_bytes()

    client.put(
        "/zones",
        json={
            "expected_version": version,
            "zones": [{**VALID_ZONE, "points": [[0.1, 0.1], [0.3, 0.3], [0.1, 0.3], [0.3, 0.1]]}],
        },
    )

    assert runtime_path.read_bytes() == before


# ============ 타입 엄격 검증 ============


@pytest.mark.parametrize(
    "rules",
    [
        {"enter_alert": "false", "dwell_threshold_sec": 5},
        {"enter_alert": "true", "dwell_threshold_sec": 5},
        {"enter_alert": 1, "dwell_threshold_sec": 5},
        {"enter_alert": True, "dwell_threshold_sec": "5"},
        {"enter_alert": True, "dwell_threshold_sec": 5.0},
        {"enter_alert": True, "dwell_threshold_sec": True},
    ],
    ids=["str_false", "str_true", "int_flag", "str_dwell", "float_dwell", "bool_dwell"],
)
def test_rules_type_coercion_is_rejected(client, runtime_path, rules):
    """`enter_alert`는 boolean, `dwell_threshold_sec`은 integer여야 한다.

    Pydantic 기본 coercion은 `"false"`를 `False`로, `"5"`를 `5`로 바꿔 저장한다.
    동결 계약은 타입을 명시하므로 잘못된 타입은 `422`여야 한다.
    """
    put_invalid(client, runtime_path, {"rules": rules})


@pytest.mark.parametrize(
    "points",
    [
        [["0.1", "0.2"], [0.3, 0.2], [0.3, 0.5]],
        [[0.1, 0.2], [0.3, "0.2"], [0.3, 0.5]],
        [[True, 0.2], [0.3, 0.2], [0.3, 0.5]],
        [[0.1, 0.2], [0.3, 0.2], [0.3, False]],
    ],
    ids=["str_pair", "str_single", "bool_first", "bool_last"],
)
def test_coordinate_type_coercion_is_rejected(client, runtime_path, points):
    """문자열·boolean 좌표를 number로 자동 변환하지 않는다."""
    put_invalid(client, runtime_path, {"points": points})


def test_integer_coordinates_are_accepted(client, runtime_path):
    """JSON 정수 좌표는 유효한 number다 (`[0, 1]`)."""
    version = seed_and_get_version(client, runtime_path)
    zone = {**VALID_ZONE, "points": [[0, 0], [1, 0], [1, 1]]}

    response = client.put(
        "/zones", json={"expected_version": version, "zones": [zone]}
    )

    assert response.status_code == 200, response.text
    assert response.json()["data"]["zones"][0]["points"] == [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0]]


@pytest.mark.parametrize(
    "overrides",
    [
        {"zone_id": 1},
        {"zone_name": 1},
        {"type": 1},
        {"zone_type": 1},
    ],
    ids=["zone_id", "zone_name", "type", "zone_type"],
)
def test_non_string_identifier_is_rejected(client, runtime_path, overrides):
    put_invalid(client, runtime_path, overrides)


def test_non_string_expected_version_is_rejected(client, runtime_path):
    write_runtime(runtime_path, [runtime_zone()])

    response = client.put("/zones", json={"expected_version": 123, "zones": [VALID_ZONE]})

    assert response.status_code == 422


def test_type_rejection_does_not_modify_file(client, runtime_path):
    """타입 오류로 거부될 때 runtime 파일이 바뀌지 않아야 한다."""
    version = seed_and_get_version(client, runtime_path)
    before = runtime_path.read_bytes()

    response = client.put(
        "/zones",
        json={
            "expected_version": version,
            "zones": [
                {
                    **VALID_ZONE,
                    "rules": {"enter_alert": "false", "dwell_threshold_sec": "5"},
                }
            ],
        },
    )

    assert response.status_code == 422
    assert runtime_path.read_bytes() == before


# ============ 파일 권한 ============


def test_put_preserves_runtime_file_mode(client, runtime_path):
    """저장 후에도 기존 권한이 유지돼야 한다.

    `tempfile.mkstemp()`는 `0600`으로 만든다. 그대로 교체하면 Docker Backend가
    쓴 파일을 host Vision AI가 읽지 못한다.
    """
    version = seed_and_get_version(client, runtime_path)
    os.chmod(runtime_path, 0o644)

    response = client.put(
        "/zones", json={"expected_version": version, "zones": [VALID_ZONE]}
    )

    assert response.status_code == 200
    assert stat.S_IMODE(runtime_path.stat().st_mode) == 0o644


def test_put_preserves_group_readable_mode(client, runtime_path):
    version = seed_and_get_version(client, runtime_path)
    os.chmod(runtime_path, 0o664)

    client.put("/zones", json={"expected_version": version, "zones": [VALID_ZONE]})

    assert stat.S_IMODE(runtime_path.stat().st_mode) == 0o664


def test_seed_copy_is_readable_by_other_processes(runtime_path):
    """setup이 만든 파일도 Vision AI가 읽을 수 있어야 한다."""
    zone_store.ensure_runtime_file()

    mode = stat.S_IMODE(runtime_path.stat().st_mode)

    assert mode & stat.S_IROTH, f"other-readable 권한이 없다: {mode:o}"


def test_put_on_missing_runtime_file_returns_500(client, runtime_path):
    assert not runtime_path.exists()

    response = client.put(
        "/zones",
        json={"expected_version": "sha256:" + "a" * 64, "zones": [VALID_ZONE]},
    )

    assert response.status_code == 500
    assert response.json() == unavailable_body()


# ============ setup·경로 ============


def test_api_does_not_create_missing_runtime_file(client, runtime_path):
    client.get("/zones")

    assert not runtime_path.exists()


def test_ensure_runtime_file_copies_seed(runtime_path):
    path = zone_store.ensure_runtime_file()

    assert path == runtime_path
    assert runtime_path.is_file()
    assert json.loads(runtime_path.read_text(encoding="utf-8"))


def test_ensure_runtime_file_does_not_overwrite(runtime_path):
    write_runtime(runtime_path, [])

    zone_store.ensure_runtime_file()

    assert json.loads(runtime_path.read_text(encoding="utf-8")) == []


def test_seed_file_is_never_written(client, runtime_path):
    seed = zone_store.get_seed_path()
    before = seed.read_bytes()
    version = seed_and_get_version(client, runtime_path)

    client.put("/zones", json={"expected_version": version, "zones": [VALID_ZONE]})

    assert seed.read_bytes() == before


def test_runtime_path_follows_environment(monkeypatch, tmp_path):
    target = tmp_path / "custom" / "zones.json"
    monkeypatch.setenv("KIDCAFE_ZONES_PATH", str(target))

    assert zone_store.get_runtime_path() == target


def test_saved_file_is_loadable_by_vision_ai(client, runtime_path):
    """저장 결과를 Vision AI가 재시작 후 그대로 읽을 수 있어야 한다.

    Backend와 Vision AI가 같은 runtime 파일을 공유하므로, 저장 형식이 어긋나면
    화면에는 반영됐는데 실제 판정은 안 바뀌는 상태가 된다.
    """
    from src.geofencing.zone_loader import load_zones

    version = seed_and_get_version(client, runtime_path)
    saved_zone = {
        **VALID_ZONE,
        "zone_id": "exit_area",
        "zone_name": "출입구",
        "zone_type": "exit",
        "rules": {"enter_alert": False, "dwell_threshold_sec": 0},
    }

    assert (
        client.put(
            "/zones", json={"expected_version": version, "zones": [saved_zone]}
        ).status_code
        == 200
    )

    zones = load_zones(str(runtime_path))

    assert len(zones) == 1
    assert zones[0].zone_id == "exit_area"
    assert zones[0].name == "출입구"
    assert zones[0].zone_type == "exit"
    assert zones[0].rules.enter_alert is False
    assert zones[0].rules.dwell_threshold_sec == 0


def test_atomic_write_leaves_no_temp_file(client, runtime_path):
    version = seed_and_get_version(client, runtime_path)

    client.put("/zones", json={"expected_version": version, "zones": [VALID_ZONE]})

    leftovers = [p.name for p in runtime_path.parent.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == []
