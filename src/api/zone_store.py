"""Zone Settings runtime 파일 저장소 (Phase 4).

seed(`data/zones/sample.json`)는 읽기 전용이고, 실제 편집 대상은 runtime
파일이다. version은 runtime 파일 bytes의 SHA-256이며 동시 수정 감지에 쓴다.

계약: docs/api_contract.md `GET /zones Phase 4 계약`, `PUT /zones Phase 4 저장 계약`
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from src.api.database import get_project_root
from src.common.types import VALID_ZONE_TYPES
from src.geofencing.polygon_rules import validate_polygon_points

VERSION_PREFIX = "sha256:"
MAX_DWELL_THRESHOLD_SEC = 3600
NORMALIZED_RANGE = (0.0, 1.0)

UNAVAILABLE_MESSAGE = "zone configuration is unavailable"
CONFLICT_MESSAGE = "zone configuration version conflict"
SAVE_FAILED_MESSAGE = "failed to save zone configuration"

# runtime 파일을 새로 만들 때 적용할 권한. Docker Backend가 쓰고 host Vision AI가
# 읽는 공유 파일이라 소유자 외에도 읽을 수 있어야 한다.
DEFAULT_RUNTIME_FILE_MODE = 0o644

# 단일 Backend process 기준 계약이다. version 확인·검증·임시 파일 작성·os.replace()를
# 하나의 임계 구역에서 수행해 lost update를 막는다.
_WRITE_LOCK = threading.Lock()


class ZoneStoreError(Exception):
    """Runtime Zone 설정을 읽거나 쓸 수 없음."""


class ZoneConfigUnavailableError(ZoneStoreError):
    """파일 누락·읽기 실패·JSON 또는 schema 오류 (generic 500 대상)."""


class ZoneVersionConflictError(ZoneStoreError):
    """`expected_version`이 현재 runtime version과 다름 (409 대상)."""


class ZoneSaveError(ZoneStoreError):
    """검증은 통과했지만 저장에 실패함 (generic 500 대상)."""


@dataclass(frozen=True)
class ZoneConfig:
    """API가 반환하는 Zone 설정 envelope."""

    version: str
    updated_at: str
    zones: List[Dict[str, Any]]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "updated_at": self.updated_at,
            "zones": self.zones,
        }


def get_seed_path() -> Path:
    """읽기 전용 seed. 최초 setup에서 runtime으로 복사할 때만 사용한다."""
    return get_project_root() / "data" / "zones" / "sample.json"


def get_runtime_path() -> Path:
    """편집 대상 runtime 파일. `KIDCAFE_ZONES_PATH`로 바꿀 수 있다."""
    env_path = os.getenv("KIDCAFE_ZONES_PATH")
    if env_path:
        return Path(env_path)
    return get_project_root() / "outputs" / "zones_runtime.json"


def compute_version(raw: bytes) -> str:
    """runtime 파일 bytes의 SHA-256을 opaque version token으로 만든다."""
    return f"{VERSION_PREFIX}{hashlib.sha256(raw).hexdigest()}"


def _format_updated_at(path: Path) -> str:
    """runtime 파일 최종 변경 시각을 UTC RFC 3339로 반환."""
    modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return modified.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _to_api_zone(zone: Dict[str, Any]) -> Dict[str, Any]:
    """runtime 내부 표현(`name`)을 API 표현(`zone_name`)으로 변환."""
    return {
        "zone_id": zone["zone_id"],
        "zone_name": zone["name"],
        "type": zone["type"],
        "zone_type": zone["zone_type"],
        "points": [[float(x), float(y)] for x, y in zone["points"]],
        "rules": {
            "enter_alert": bool(zone["rules"]["enter_alert"]),
            "dwell_threshold_sec": int(zone["rules"]["dwell_threshold_sec"]),
        },
    }


def _to_runtime_zone(zone: Dict[str, Any]) -> Dict[str, Any]:
    """API 표현(`zone_name`)을 runtime 내부 표현(`name`)으로 변환.

    Vision AI의 `zone_loader`가 그대로 읽을 수 있는 형태를 유지한다.
    """
    return {
        "zone_id": zone["zone_id"],
        "name": zone["zone_name"],
        "type": zone["type"],
        "zone_type": zone["zone_type"],
        "points": [[float(x), float(y)] for x, y in zone["points"]],
        "rules": {
            "enter_alert": bool(zone["rules"]["enter_alert"]),
            "dwell_threshold_sec": int(zone["rules"]["dwell_threshold_sec"]),
        },
    }


def _validate_runtime_payload(data: Any) -> List[Dict[str, Any]]:
    """runtime 파일 내용이 Zone 목록 계약을 만족하는지 확인.

    Raises:
        ZoneConfigUnavailableError: 형식·필드·좌표 오류
    """
    if not isinstance(data, list):
        raise ZoneConfigUnavailableError("zone configuration must be a JSON array")

    seen_ids = set()
    zones: List[Dict[str, Any]] = []
    for idx, item in enumerate(data):
        if not isinstance(item, dict):
            raise ZoneConfigUnavailableError(f"zone #{idx} must be an object")

        for field in ("zone_id", "name", "type", "zone_type", "points"):
            if field not in item:
                raise ZoneConfigUnavailableError(f"zone #{idx} missing field: '{field}'")

        zone_id = item["zone_id"]
        if not isinstance(zone_id, str) or not zone_id.strip():
            raise ZoneConfigUnavailableError(f"zone #{idx} zone_id must be a non-empty string")
        if zone_id in seen_ids:
            raise ZoneConfigUnavailableError(f"duplicate zone_id: '{zone_id}'")
        seen_ids.add(zone_id)

        if not isinstance(item["name"], str) or not item["name"].strip():
            raise ZoneConfigUnavailableError(f"zone '{zone_id}' name must be a non-empty string")
        if item["type"] != "polygon":
            raise ZoneConfigUnavailableError(f"zone '{zone_id}' type must be 'polygon'")
        if item["zone_type"] not in VALID_ZONE_TYPES:
            raise ZoneConfigUnavailableError(f"zone '{zone_id}' has invalid zone_type")

        try:
            points = validate_polygon_points(
                item["points"],
                coordinate_range=NORMALIZED_RANGE,
                label=f"zone '{zone_id}' points",
            )
        except ValueError as e:
            raise ZoneConfigUnavailableError(str(e))

        rules = item.get("rules", {})
        if not isinstance(rules, dict):
            raise ZoneConfigUnavailableError(f"zone '{zone_id}' rules must be an object")
        enter_alert = rules.get("enter_alert", True)
        dwell = rules.get("dwell_threshold_sec", 5)
        if not isinstance(enter_alert, bool):
            raise ZoneConfigUnavailableError(f"zone '{zone_id}' enter_alert must be a boolean")
        if not isinstance(dwell, int) or isinstance(dwell, bool):
            raise ZoneConfigUnavailableError(
                f"zone '{zone_id}' dwell_threshold_sec must be an integer"
            )
        if not (0 <= dwell <= MAX_DWELL_THRESHOLD_SEC):
            raise ZoneConfigUnavailableError(
                f"zone '{zone_id}' dwell_threshold_sec out of range"
            )

        zones.append(
            {
                "zone_id": zone_id,
                "name": item["name"],
                "type": item["type"],
                "zone_type": item["zone_type"],
                "points": points,
                "rules": {
                    "enter_alert": enter_alert,
                    "dwell_threshold_sec": dwell,
                },
            }
        )

    return zones


def _read_runtime() -> tuple[List[Dict[str, Any]], str, str]:
    """runtime 파일을 읽어 (내부 zone 목록, version, updated_at)을 반환.

    파일이 없어도 자동 생성하지 않는다. setup 단계가 seed를 복사해야 한다.

    Raises:
        ZoneConfigUnavailableError: 누락·읽기 실패·JSON 또는 schema 오류
    """
    path = get_runtime_path()
    if not path.is_file():
        raise ZoneConfigUnavailableError(f"runtime zone file not found: {path}")

    try:
        raw = path.read_bytes()
    except OSError as e:
        raise ZoneConfigUnavailableError(f"failed to read {path}: {e}")

    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ZoneConfigUnavailableError(f"invalid JSON in {path}: {e}")

    zones = _validate_runtime_payload(data)
    return zones, compute_version(raw), _format_updated_at(path)


def load_zone_config() -> ZoneConfig:
    """현재 runtime Zone 설정을 API 표현으로 반환.

    유효한 빈 파일(`[]`)은 `zones=[]`로 정상 응답한다. 오류를 빈 Zone이나 Mock
    데이터로 대체하지 않는다.

    Raises:
        ZoneConfigUnavailableError: 읽을 수 없거나 계약 위반
    """
    zones, version, updated_at = _read_runtime()
    return ZoneConfig(
        version=version,
        updated_at=updated_at,
        zones=[_to_api_zone(zone) for zone in zones],
    )


def save_zone_config(expected_version: str, api_zones: List[Dict[str, Any]]) -> ZoneConfig:
    """전체 Zone 목록을 교체 저장한다.

    version 확인, 임시 파일 작성, `os.replace()`를 하나의 lock 임계 구역에서
    수행한다. 요청에 없는 Zone은 삭제된다.

    Raises:
        ZoneConfigUnavailableError: 현재 설정을 읽을 수 없음
        ZoneVersionConflictError: `expected_version` 불일치
        ZoneSaveError: 저장 실패
    """
    path = get_runtime_path()
    payload = [_to_runtime_zone(zone) for zone in api_zones]
    serialized = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")

    with _WRITE_LOCK:
        _, current_version, _ = _read_runtime()
        if expected_version != current_version:
            raise ZoneVersionConflictError(CONFLICT_MESSAGE)

        try:
            _atomic_write(path, serialized)
        except OSError as e:
            raise ZoneSaveError(f"failed to write {path}: {e}")

        return ZoneConfig(
            version=compute_version(serialized),
            updated_at=_format_updated_at(path),
            zones=[_to_api_zone(zone) for zone in payload],
        )


def _atomic_write(path: Path, data: bytes) -> None:
    """같은 디렉터리에 임시 파일을 쓰고 `os.replace()`로 교체한다.

    교체가 실패해도 기존 파일은 그대로 남는다. 임시 파일은 같은 파일시스템에
    두어야 `os.replace()`가 원자적으로 동작한다.

    권한은 기존 파일 것을 그대로 물려준다. `tempfile.mkstemp()`가 만드는 파일은
    `0600`이라 교체만 하면 Docker Backend가 쓴 파일을 host Vision AI가 읽지
    못하게 된다. 두 프로세스가 같은 runtime 파일을 공유하는 구조라 치명적이다.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = (
        stat.S_IMODE(path.stat().st_mode)
        if path.is_file()
        else DEFAULT_RUNTIME_FILE_MODE
    )

    descriptor, temp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_path, mode)
        os.replace(temp_path, path)
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise


def ensure_runtime_file() -> Path:
    """runtime 파일이 없으면 seed를 복사한다 (setup 전용).

    API 요청 경로에서는 호출하지 않는다. 계약상 API는 누락 파일을 자동
    생성하지 않는다.

    Raises:
        ZoneStoreError: seed가 없거나 복사에 실패함
    """
    path = get_runtime_path()
    if path.is_file():
        return path

    seed = get_seed_path()
    if not seed.is_file():
        raise ZoneStoreError(f"seed zone file not found: {seed}")

    try:
        _atomic_write(path, seed.read_bytes())
    except OSError as e:
        raise ZoneStoreError(f"failed to copy seed to {path}: {e}")

    return path
