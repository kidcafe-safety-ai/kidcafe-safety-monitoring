"""Zone definition route."""

from __future__ import annotations

import json

from fastapi import APIRouter

from src.api.database import get_project_root
from src.api.schemas import ZonesResponse, success_response


router = APIRouter()


def _normalize_zones(zones):
    normalized = []
    for zone in zones:
        if not isinstance(zone, dict):
            continue
        item = dict(zone)
        if "zone_name" not in item and "name" in item:
            item["zone_name"] = item["name"]
        normalized.append(item)
    return normalized


@router.get("/zones", response_model=ZonesResponse)
def get_zones():
    zones_path = get_project_root() / "data" / "zones" / "sample.json"
    try:
        zones = json.loads(zones_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        zones = []

    if not isinstance(zones, list):
        zones = []

    return success_response(_normalize_zones(zones))
