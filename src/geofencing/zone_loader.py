"""Zone 정의 파일 로더."""

import json
from pathlib import Path
from typing import List

from src.common.types import Zone, ZoneRules


def load_zones(json_path: str) -> List[Zone]:
    """JSON 파일에서 Zone 리스트를 로드."""
    path = Path(json_path)
    if not path.exists():
        raise FileNotFoundError(f"Zone file not found: {json_path}")

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    zones = []
    for item in data:
        rules_data = item.get("rules", {})
        rules = ZoneRules(
            enter_alert=rules_data.get("enter_alert", True),
            dwell_threshold_sec=rules_data.get("dwell_threshold_sec", 5),
        )
        zone = Zone(
            zone_id=item["zone_id"],
            name=item["name"],
            type=item["type"],
            points=item["points"],
            rules=rules,
        )
        zones.append(zone)

    return zones