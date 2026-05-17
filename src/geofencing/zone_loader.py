"""Zone 정의 파일 로더 (검증 강화)."""

import json
from pathlib import Path
from typing import List

from src.common.types import Zone, ZoneRules


def load_zones(json_path: str) -> List[Zone]:
    """JSON 파일에서 Zone 리스트를 로드.

    Validations:
        - 파일 존재 여부
        - JSON 파싱 가능 여부
        - 필수 필드 (zone_id, name, type, points)
        - 좌표 0~1 범위
        - polygon은 최소 3점

    Raises:
        FileNotFoundError: 파일이 없음
        ValueError: JSON 형식 오류, 좌표 범위 초과, 등
    """
    path = Path(json_path)
    if not path.exists():
        raise FileNotFoundError(f"Zone file not found: {json_path}")

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in {json_path}: {e}")

    if not isinstance(data, list):
        raise ValueError(f"{json_path} must contain a JSON array")

    zones = []
    for idx, item in enumerate(data):
        # 필수 필드 체크
        for required in ("zone_id", "name", "type", "points"):
            if required not in item:
                raise ValueError(
                    f"Zone #{idx} missing required field: '{required}'"
                )

        # 좌표 0~1 범위 검증
        for pt_idx, pt in enumerate(item["points"]):
            if not isinstance(pt, list) or len(pt) != 2:
                raise ValueError(
                    f"Zone '{item['zone_id']}' point #{pt_idx} "
                    f"must be [x, y] list"
                )
            x, y = pt
            if not (0.0 <= x <= 1.0) or not (0.0 <= y <= 1.0):
                raise ValueError(
                    f"Zone '{item['zone_id']}' point #{pt_idx} "
                    f"out of normalized range [0,1]: got ({x}, {y})"
                )

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