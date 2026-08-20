"""`docs/phase4_backend_freeze.md`가 동결한 값이 실제 코드와 같은지 본다.

문서로만 남긴 동결은 지켜지지 않는다. 누가 상수 하나를 바꿔도 문서는 그대로
남고, 제출물의 "실행·재현 안내"가 실제 동작과 어긋난 채로 나간다. 그래서 동결
값을 코드에서 직접 읽어 문서에 적힌 값과 대조한다.

값을 바꿔야 하면 문서와 이 테스트를 함께 고친다. 한쪽만 고치면 CI가 걸린다.
그 마찰이 이 테스트의 목적이다.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FREEZE_DOC = ROOT / "docs" / "phase4_backend_freeze.md"


@pytest.fixture(scope="module")
def doc() -> str:
    return FREEZE_DOC.read_text(encoding="utf-8")


def test_freeze_document_exists(doc):
    assert "동결 기준 커밋" in doc
    assert "변경 이력" in doc


# --- RTSP 상수 ---


@pytest.mark.parametrize(
    "name, expected",
    [
        ("_RTSP_FPS_FALLBACK", 25.0),
        ("_RTSP_READ_WAIT_SEC", 0.05),
        ("_RTSP_STALE_TIMEOUT_SEC", 3.0),
        ("_RTSP_MAX_CONSECUTIVE_READ_FAILURES", 30),
        ("_RTSP_RELEASE_JOIN_TIMEOUT_SEC", 2.0),
    ],
)
def test_rtsp_constants_match_the_freeze(name, expected, doc):
    from src.input import rtsp_source

    assert getattr(rtsp_source, name) == expected
    assert f"`{name}`" in doc, f"{name}이 동결 문서에 없습니다"


def test_rtsp_uses_tcp_transport(doc):
    """UDP는 무선 구간에서 프레임을 잃고, 손실이 Event 시간축을 흔든다."""
    from src.input import rtsp_source

    options = rtsp_source._OPENCV_FFMPEG_CAPTURE_OPTIONS
    assert "rtsp_transport;tcp" in options
    assert "stimeout;5000000" in options
    assert options in doc


def test_rtsp_credential_env_names_match_the_freeze(doc):
    from src.input import rtsp_source

    assert rtsp_source.RTSP_USERNAME_ENV == "KIDCAFE_RTSP_USERNAME"
    assert rtsp_source.RTSP_PASSWORD_ENV == "KIDCAFE_RTSP_PASSWORD"
    assert "`KIDCAFE_RTSP_USERNAME`" in doc
    assert "`KIDCAFE_RTSP_PASSWORD`" in doc


# --- Event 판정 상수 ---


@pytest.mark.parametrize(
    "name, expected",
    [
        ("DEFAULT_ENTER_CONFIRM_SEC", 0.3),
        ("DEFAULT_EXIT_CONFIRM_SEC", 0.5),
        ("DEFAULT_TRACK_LOST_GRACE_SEC", 0.5),
    ],
)
def test_event_debounce_constants_match_the_freeze(name, expected, doc):
    from src.events import event_manager

    assert getattr(event_manager, name) == expected
    assert f"`{name}`" in doc


# --- Backend 경로 ---


def test_backend_env_variable_names_match_the_freeze(doc):
    """경로 환경변수 이름이 바뀌면 Docker 구성과 문서가 동시에 깨진다."""
    database = (ROOT / "src" / "api" / "database.py").read_text(encoding="utf-8")
    zone_store = (ROOT / "src" / "api" / "zone_store.py").read_text(encoding="utf-8")

    assert "KIDCAFE_DB_PATH" in database
    assert "KIDCAFE_ZONES_PATH" in zone_store
    for name in ("KIDCAFE_DB_PATH", "KIDCAFE_ZONES_PATH"):
        assert f"`{name}`" in doc


def test_compose_defaults_match_the_freeze(doc):
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "/app/outputs/kidcafe_events.db" in compose
    assert "/app/outputs/zones_runtime.json" in compose
    assert "/app/outputs/kidcafe_events.db" in doc
    assert "/app/outputs/zones_runtime.json" in doc


def test_zone_runtime_default_path_matches_the_freeze(doc):
    """Vision AI의 --zones와 API의 runtime 경로가 갈리면 저장이 반영되지 않는다."""
    zone_store = (ROOT / "src" / "api" / "zone_store.py").read_text(encoding="utf-8")
    assert '"outputs"' in zone_store and '"zones_runtime.json"' in zone_store
    assert "outputs/zones_runtime.json" in doc


# --- 낙상 기본 비활성 ---


def test_fall_detection_stays_opt_in(doc):
    """계획서 4절: 운영 목표 충족 전까지 기본 비활성으로 유지한다."""
    main_source = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
    assert "set_defaults(fall_detection_enabled=False)" in main_source
    assert "비활성" in doc


# --- 의존성 핀 ---


def pinned_versions(path: Path) -> dict:
    versions = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        match = re.match(r"^([A-Za-z0-9_.\-]+)(?:\[[^\]]+\])?==([0-9][^\s]*)$", line)
        if match:
            versions[match.group(1).lower()] = match.group(2)
    return versions


@pytest.mark.parametrize(
    "package, expected",
    [
        ("torch", "2.5.1"),
        ("ultralytics", "8.4.56"),
        ("opencv-python", "4.8.1.78"),
        ("shapely", "2.0.1"),
        ("numpy", "1.26.4"),
        ("fastapi", "0.111.0"),
        ("pydantic", "2.7.1"),
    ],
)
def test_pinned_dependency_matches_the_freeze(package, expected, doc):
    versions = pinned_versions(ROOT / "requirements.txt")
    assert versions.get(package) == expected, f"{package} 핀이 동결과 다릅니다"
    assert f"`{expected}`" in doc


def test_api_requirements_keep_the_numpy_pin():
    """이 핀이 없으면 pip이 numpy 2.x를 끌어와 API가 import 단계에서 죽는다.

    shapely 2.0.1 휠이 numpy 1.x로 빌드돼 있어서 생기는 문제라, 핀을 지우면
    컨테이너가 기동되지 않는다. 실제로 겪은 장애라 회귀로 막는다.
    """
    versions = pinned_versions(ROOT / "requirements-api.txt")
    assert versions.get("numpy") == "1.26.4"
    assert versions.get("shapely") == "2.0.1"


def test_api_and_vision_pins_agree():
    """두 requirements가 갈리면 컨테이너와 로컬 실행 결과가 달라진다."""
    api = pinned_versions(ROOT / "requirements-api.txt")
    vision = pinned_versions(ROOT / "requirements.txt")
    for package, version in api.items():
        if package in vision:
            assert vision[package] == version, f"{package} 버전이 두 파일에서 다릅니다"


def test_router_order_matches_the_freeze(doc):
    """문서가 적은 라우터 순서가 실제 등록 순서와 같아야 한다."""
    main_source = (ROOT / "src" / "api" / "main.py").read_text(encoding="utf-8")
    actual = re.findall(r"app\.include_router\((\w+)\.router\)", main_source)
    assert ", ".join(actual) in doc, f"실제 순서는 {actual}입니다"
