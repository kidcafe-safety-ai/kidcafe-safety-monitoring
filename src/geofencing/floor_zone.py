"""Floor-plane(meter) Zone 정의 로더와 판정기 (Phase 4 Homography PoC).

`data/zones/floor_<camera_id>.json`을 읽어 meter 좌표 Zone을 만든다. 기존
image-normalized Zone 경로(`zone_loader`·`ZoneChecker`)는 그대로 두고, 이
모듈은 비교용 PoC 경로로만 사용한다.

계약: docs/interfaces.md `Floor Zone PoC 파일`
좌표계·채택 기준: docs/homography_calibration.md
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Sequence

from shapely.geometry import Point, Polygon

from src.common.types import VALID_ZONE_TYPES, ZoneRules
from src.geofencing.polygon_rules import validate_polygon_points

SCHEMA_VERSION = 1
COORDINATE_SPACE = "floor_meters"

MAX_DWELL_THRESHOLD_SEC = 3600


class FloorZoneError(ValueError):
    """Floor Zone 설정이 계약을 만족하지 않음."""


@dataclass
class FloorZone:
    """meter 좌표계 Zone."""

    zone_id: str
    zone_name: str
    type: str
    zone_type: str
    points: List[List[float]]
    rules: ZoneRules


@dataclass
class FloorZoneConfig:
    camera_id: str
    schema_version: int
    coordinate_space: str
    zones: List[FloorZone]


def parse_floor_zones(data: dict) -> FloorZoneConfig:
    """dict를 검증해 `FloorZoneConfig`로 변환.

    Raises:
        FloorZoneError: schema·좌표계·polygon·rules 계약 위반
    """
    if not isinstance(data, dict):
        raise FloorZoneError("floor zone config must be a JSON object")

    for field in ("schema_version", "camera_id", "coordinate_space", "zones"):
        if field not in data:
            raise FloorZoneError(f"missing required field: '{field}'")

    if data["schema_version"] != SCHEMA_VERSION:
        raise FloorZoneError(
            f"unsupported schema_version: {data['schema_version']} (expected {SCHEMA_VERSION})"
        )
    if data["coordinate_space"] != COORDINATE_SPACE:
        raise FloorZoneError(
            f"coordinate_space must be '{COORDINATE_SPACE}': got '{data['coordinate_space']}'"
        )
    if not isinstance(data["camera_id"], str) or not data["camera_id"].strip():
        raise FloorZoneError("'camera_id' must be a non-empty string")
    if not isinstance(data["zones"], list):
        raise FloorZoneError("'zones' must be a list")

    zones: List[FloorZone] = []
    seen_ids = set()
    for idx, item in enumerate(data["zones"]):
        zone = _parse_zone(item, idx)
        if zone.zone_id in seen_ids:
            raise FloorZoneError(f"duplicate zone_id: '{zone.zone_id}'")
        seen_ids.add(zone.zone_id)
        zones.append(zone)

    return FloorZoneConfig(
        camera_id=data["camera_id"],
        schema_version=data["schema_version"],
        coordinate_space=data["coordinate_space"],
        zones=zones,
    )


def _parse_zone(item, idx: int) -> FloorZone:
    if not isinstance(item, dict):
        raise FloorZoneError(f"zone #{idx} must be an object")

    for field in ("zone_id", "zone_name", "type", "zone_type", "points"):
        if field not in item:
            raise FloorZoneError(f"zone #{idx} missing required field: '{field}'")

    for field in ("zone_id", "zone_name"):
        value = item[field]
        if not isinstance(value, str) or not value.strip():
            raise FloorZoneError(f"zone #{idx} '{field}' must be a non-empty string")

    zone_id = item["zone_id"]
    if item["type"] != "polygon":
        raise FloorZoneError(f"zone '{zone_id}' type must be 'polygon': got '{item['type']}'")
    if item["zone_type"] not in VALID_ZONE_TYPES:
        raise FloorZoneError(
            f"zone '{zone_id}' zone_type must be one of "
            f"{sorted(VALID_ZONE_TYPES)}: got '{item['zone_type']}'"
        )

    # floor 좌표는 meter라 상한이 없다. 범위 제한은 걸지 않는다.
    try:
        points = validate_polygon_points(item["points"], label=f"zone '{zone_id}' points")
    except ValueError as e:
        raise FloorZoneError(str(e))

    return FloorZone(
        zone_id=zone_id,
        zone_name=item["zone_name"],
        type=item["type"],
        zone_type=item["zone_type"],
        points=points,
        rules=_parse_rules(item.get("rules", {}), zone_id),
    )


def _parse_rules(rules_data, zone_id: str) -> ZoneRules:
    if not isinstance(rules_data, dict):
        raise FloorZoneError(f"zone '{zone_id}' rules must be an object")

    enter_alert = rules_data.get("enter_alert", True)
    if not isinstance(enter_alert, bool):
        raise FloorZoneError(f"zone '{zone_id}' rules.enter_alert must be a boolean")

    dwell = rules_data.get("dwell_threshold_sec", 5)
    if not isinstance(dwell, int) or isinstance(dwell, bool):
        raise FloorZoneError(f"zone '{zone_id}' rules.dwell_threshold_sec must be an integer")
    if not (0 <= dwell <= MAX_DWELL_THRESHOLD_SEC):
        raise FloorZoneError(
            f"zone '{zone_id}' rules.dwell_threshold_sec must be in "
            f"[0, {MAX_DWELL_THRESHOLD_SEC}]: got {dwell}"
        )

    return ZoneRules(enter_alert=enter_alert, dwell_threshold_sec=dwell)


def load_floor_zones(json_path: str) -> FloorZoneConfig:
    """Floor Zone 설정 파일을 로드해 검증.

    Raises:
        FileNotFoundError: 파일이 없음
        FloorZoneError: JSON 형식 오류 또는 계약 위반
    """
    path = Path(json_path)
    if not path.exists():
        raise FileNotFoundError(f"Floor zone file not found: {json_path}")

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise FloorZoneError(f"Invalid JSON in {json_path}: {e}")

    return parse_floor_zones(data)


class FloorZoneChecker:
    """meter 단위 floor point가 어느 Zone 안에 있는지 판정.

    기존 `ZoneChecker`와 동일하게 `covers()`로 경계를 포함해 판정한다. 차이는
    입력이 정규화 픽셀이 아니라 이미 변환된 floor 좌표라는 점뿐이다.
    """

    def __init__(self, config: FloorZoneConfig):
        self.config = config
        self.polygons: Dict[str, Polygon] = {
            zone.zone_id: Polygon(zone.points) for zone in config.zones
        }

    @property
    def camera_id(self) -> str:
        return self.config.camera_id

    def check_point(self, floor_point: Sequence[float]) -> List[str]:
        """floor 좌표가 들어있는 zone_id 리스트를 정의 순서대로 반환."""
        if not isinstance(floor_point, (list, tuple)) or len(floor_point) != 2:
            raise ValueError("floor_point must be an [x, y] pair")

        point = Point(float(floor_point[0]), float(floor_point[1]))
        return [
            zone.zone_id
            for zone in self.config.zones
            if self.polygons[zone.zone_id].covers(point)
        ]
