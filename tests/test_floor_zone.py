"""Floor-plane Zone 로더·판정기 테스트 (Phase 4 Homography PoC)."""

import copy
import json

import pytest

from src.geofencing.floor_zone import (
    FloorZoneChecker,
    FloorZoneError,
    load_floor_zones,
    parse_floor_zones,
)

FIXTURE_PATH = "tests/fixtures/phase4_contract/floor_zone_config.json"


@pytest.fixture
def config_data():
    with open(FIXTURE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def checker(config_data):
    return FloorZoneChecker(parse_floor_zones(config_data))


# ============ 로드·검증 ============


def test_parse_contract_fixture(config_data):
    config = parse_floor_zones(config_data)

    assert config.camera_id == "cam01"
    assert config.coordinate_space == "floor_meters"
    assert len(config.zones) == 1

    zone = config.zones[0]
    assert zone.zone_id == "danger_door_floor"
    assert zone.zone_name == "출입문 위험구역"
    assert zone.zone_type == "danger"
    assert zone.rules.enter_alert is True
    assert zone.rules.dwell_threshold_sec == 5


@pytest.mark.parametrize("field", ["schema_version", "camera_id", "coordinate_space", "zones"])
def test_missing_required_field(config_data, field):
    data = copy.deepcopy(config_data)
    del data[field]

    with pytest.raises(FloorZoneError, match=f"'{field}'"):
        parse_floor_zones(data)


def test_unsupported_schema_version(config_data):
    data = copy.deepcopy(config_data)
    data["schema_version"] = 99

    with pytest.raises(FloorZoneError, match="schema_version"):
        parse_floor_zones(data)


def test_coordinate_space_must_be_floor_meters(config_data):
    """image-normalized Zone 파일을 floor 로더에 넣으면 실패해야 한다."""
    data = copy.deepcopy(config_data)
    data["coordinate_space"] = "image_normalized"

    with pytest.raises(FloorZoneError, match="coordinate_space"):
        parse_floor_zones(data)


@pytest.mark.parametrize("field", ["zone_id", "zone_name", "type", "zone_type", "points"])
def test_zone_missing_field(config_data, field):
    data = copy.deepcopy(config_data)
    del data["zones"][0][field]

    with pytest.raises(FloorZoneError, match=field):
        parse_floor_zones(data)


@pytest.mark.parametrize("field", ["zone_id", "zone_name"])
def test_blank_zone_string_rejected(config_data, field):
    data = copy.deepcopy(config_data)
    data["zones"][0][field] = "  "

    with pytest.raises(FloorZoneError, match=field):
        parse_floor_zones(data)


def test_non_polygon_type_rejected(config_data):
    data = copy.deepcopy(config_data)
    data["zones"][0]["type"] = "circle"

    with pytest.raises(FloorZoneError, match="must be 'polygon'"):
        parse_floor_zones(data)


def test_unknown_zone_type_rejected(config_data):
    data = copy.deepcopy(config_data)
    data["zones"][0]["zone_type"] = "playground"

    with pytest.raises(FloorZoneError, match="zone_type"):
        parse_floor_zones(data)


def test_duplicate_zone_id_rejected(config_data):
    data = copy.deepcopy(config_data)
    data["zones"].append(copy.deepcopy(data["zones"][0]))

    with pytest.raises(FloorZoneError, match="duplicate zone_id"):
        parse_floor_zones(data)


def test_self_intersecting_polygon_rejected(config_data):
    data = copy.deepcopy(config_data)
    data["zones"][0]["points"] = [[0.0, 0.0], [2.0, 2.0], [0.0, 2.0], [2.0, 0.0]]

    with pytest.raises(FloorZoneError, match="self-intersect"):
        parse_floor_zones(data)


def test_closed_ring_rejected(config_data):
    data = copy.deepcopy(config_data)
    points = data["zones"][0]["points"]
    data["zones"][0]["points"] = points + [list(points[0])]

    with pytest.raises(FloorZoneError, match="open ring"):
        parse_floor_zones(data)


def test_meter_coordinates_above_one_are_allowed(config_data):
    """floor 좌표는 정규화 좌표가 아니므로 1.0을 넘어도 유효하다."""
    data = copy.deepcopy(config_data)
    data["zones"][0]["points"] = [[0.0, 0.0], [6.0, 0.0], [6.0, 4.0], [0.0, 4.0]]

    config = parse_floor_zones(data)

    assert config.zones[0].points[2] == [6.0, 4.0]


@pytest.mark.parametrize("dwell", [-1, 3601, 5.5, "5"])
def test_invalid_dwell_threshold_rejected(config_data, dwell):
    data = copy.deepcopy(config_data)
    data["zones"][0]["rules"]["dwell_threshold_sec"] = dwell

    with pytest.raises(FloorZoneError, match="dwell_threshold_sec"):
        parse_floor_zones(data)


@pytest.mark.parametrize("dwell", [0, 3600])
def test_dwell_threshold_boundaries_accepted(config_data, dwell):
    data = copy.deepcopy(config_data)
    data["zones"][0]["rules"]["dwell_threshold_sec"] = dwell

    assert parse_floor_zones(data).zones[0].rules.dwell_threshold_sec == dwell


def test_non_boolean_enter_alert_rejected(config_data):
    data = copy.deepcopy(config_data)
    data["zones"][0]["rules"]["enter_alert"] = "true"

    with pytest.raises(FloorZoneError, match="enter_alert"):
        parse_floor_zones(data)


def test_rules_default_when_omitted(config_data):
    data = copy.deepcopy(config_data)
    del data["zones"][0]["rules"]

    rules = parse_floor_zones(data).zones[0].rules

    assert rules.enter_alert is True
    assert rules.dwell_threshold_sec == 5


def test_empty_zone_list_is_valid(config_data):
    data = copy.deepcopy(config_data)
    data["zones"] = []

    assert parse_floor_zones(data).zones == []


def test_load_floor_zones_from_file(tmp_path, config_data):
    path = tmp_path / "floor_cam01.json"
    path.write_text(json.dumps(config_data), encoding="utf-8")

    assert load_floor_zones(str(path)).camera_id == "cam01"


def test_load_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_floor_zones(str(tmp_path / "absent.json"))


def test_load_invalid_json_raises(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("{", encoding="utf-8")

    with pytest.raises(FloorZoneError, match="Invalid JSON"):
        load_floor_zones(str(path))


# ============ 판정 ============


def test_point_inside_zone(checker):
    assert checker.check_point([1.0, 0.75]) == ["danger_door_floor"]


def test_point_outside_zone(checker):
    assert checker.check_point([5.0, 3.0]) == []


@pytest.mark.parametrize("point", [[0.0, 0.0], [2.0, 1.5], [0.0, 1.5], [2.0, 0.0]])
def test_boundary_corner_is_inside(checker, point):
    """기존 ZoneChecker와 같이 covers()로 경계를 포함해 판정한다."""
    assert checker.check_point(point) == ["danger_door_floor"]


def test_boundary_edge_is_inside(checker):
    assert checker.check_point([1.0, 0.0]) == ["danger_door_floor"]


def test_just_outside_boundary_is_excluded(checker):
    assert checker.check_point([2.0001, 0.75]) == []


def test_overlapping_zones_return_definition_order(config_data):
    data = copy.deepcopy(config_data)
    second = copy.deepcopy(data["zones"][0])
    second["zone_id"] = "wide_play_floor"
    second["zone_name"] = "놀이 구역"
    second["zone_type"] = "play"
    second["points"] = [[0.0, 0.0], [6.0, 0.0], [6.0, 4.0], [0.0, 4.0]]
    data["zones"].append(second)

    checker = FloorZoneChecker(parse_floor_zones(data))

    assert checker.check_point([1.0, 0.75]) == ["danger_door_floor", "wide_play_floor"]


def test_camera_id_exposed(checker):
    assert checker.camera_id == "cam01"


@pytest.mark.parametrize("bad_point", [[1.0], [1.0, 2.0, 3.0], "1,2"])
def test_check_point_rejects_malformed_input(checker, bad_point):
    with pytest.raises(ValueError, match=r"\[x, y\] pair"):
        checker.check_point(bad_point)
