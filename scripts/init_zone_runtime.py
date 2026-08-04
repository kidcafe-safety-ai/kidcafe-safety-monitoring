"""Zone Settings runtime 파일을 seed에서 초기화한다 (Phase 4 setup).

API는 계약상 누락된 runtime 파일을 자동 생성하지 않는다. Backend를 처음 띄우기
전에 이 스크립트를 한 번 실행한다. 이미 파일이 있으면 덮어쓰지 않는다.

    python scripts/init_zone_runtime.py
    KIDCAFE_ZONES_PATH=/app/outputs/zones_runtime.json python scripts/init_zone_runtime.py

계약: docs/api_contract.md `PUT /zones Phase 4 저장 계약`
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.api import zone_store  # noqa: E402


def main() -> None:
    path = zone_store.get_runtime_path()
    existed = path.is_file()

    try:
        zone_store.ensure_runtime_file()
    except zone_store.ZoneStoreError as exc:
        raise SystemExit(str(exc)) from exc

    if existed:
        print(f"runtime Zone 파일이 이미 있습니다(덮어쓰지 않음): {path}")
        return

    print(f"seed를 복사했습니다: {zone_store.get_seed_path()} -> {path}")

    try:
        config = zone_store.load_zone_config()
    except zone_store.ZoneConfigUnavailableError as exc:
        raise SystemExit(f"복사한 runtime 파일을 읽을 수 없습니다: {exc}") from exc

    print(f"Zone {len(config.zones)}개, version={config.version}")


if __name__ == "__main__":
    main()
