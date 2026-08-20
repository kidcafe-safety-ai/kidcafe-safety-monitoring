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


# --- Vision AI -> API 통합 계층 ---


@pytest.mark.parametrize(
    "module, name, expected",
    [
        ("src.integrations.async_event_dispatcher", "_DEFAULT_EVENT_QUEUE_MAXSIZE", 100),
        ("src.integrations.async_event_dispatcher", "_WAIT_POLL_SEC", 0.5),
        ("src.integrations.event_api_client", "_DEFAULT_CONNECT_TIMEOUT_SEC", 0.5),
        ("src.integrations.event_api_client", "_DEFAULT_READ_TIMEOUT_SEC", 1.0),
        ("src.integrations.event_api_client", "_LOG_COOLDOWN_SEC", 5.0),
    ],
)
def test_dispatch_constants_match_the_freeze(module, name, expected, doc):
    """timeout이 길어지면 추론 루프의 프레임 예산이 깨진다."""
    import importlib

    assert getattr(importlib.import_module(module), name) == expected
    assert f"`{name}`" in doc


def test_failed_event_path_matches_the_freeze(doc):
    """API가 죽어도 Event를 잃지 않는다는 계약의 저장 위치다."""
    from src.integrations import async_event_dispatcher

    path = async_event_dispatcher._DEFAULT_FAILED_EVENTS_PATH
    assert path == "outputs/api_failed_events.jsonl"
    assert path in doc


# --- Live Frame ---


@pytest.mark.parametrize(
    "name, expected",
    [
        ("_TARGET_WIDTH", 640),
        ("_TARGET_HEIGHT", 480),
        ("_DEFAULT_QUALITY", 75),
        ("_DEFAULT_MIN_INTERVAL_SEC", 0.5),
    ],
)
def test_live_frame_client_constants_match_the_freeze(name, expected, doc):
    from src.integrations import live_frame_client

    assert getattr(live_frame_client, name) == expected


def test_live_frame_stale_timeout_matches_the_freeze(doc):
    """stale이면 204다. 빈 이미지를 만들어 내려주지 않는다."""
    from src.api import live_frame_store

    assert live_frame_store.DEFAULT_STALE_AFTER_SEC == 3.0
    assert "`DEFAULT_STALE_AFTER_SEC`" in doc


def test_live_frame_is_opt_in(doc):
    main_source = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
    assert '"--live-frame-enabled"' in main_source
    assert "live_frame_enabled: bool = False" in main_source
    assert "기본 **꺼짐**" in doc


def test_live_frame_fps_becomes_an_interval(doc):
    """1.5fps는 0.667초 간격이 된다. 클라이언트 상수 0.5는 대체값일 뿐이다."""
    main_source = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
    assert "min_interval_sec = 1.0 / live_frame_fps" in main_source
    assert "0.667" in doc


# --- RTSP 조립 기본값 ---


def test_rtsp_host_default_is_documented_as_site_specific(doc):
    """특정 망의 사설 IP가 기본값이라 다른 곳에서는 반드시 덮어써야 한다."""
    from src.input import rtsp_source

    assert rtsp_source.DEFAULT_RTSP_HOST == "192.168.0.4"
    assert rtsp_source.DEFAULT_RTSP_PORT == 554
    assert "192.168.0.4" in doc
    assert "덮어써야" in doc


# --- Zone 저장 계약 ---


def test_zone_store_constants_match_the_freeze(doc):
    from src.api import zone_store

    assert zone_store.VERSION_PREFIX == "sha256:"
    assert zone_store.MAX_DWELL_THRESHOLD_SEC == 3600
    assert zone_store.NORMALIZED_RANGE == (0.0, 1.0)
    assert zone_store.DEFAULT_RUNTIME_FILE_MODE == 0o644
    assert "`3600`초" in doc
    assert "`0o644`" in doc


def test_zone_save_is_atomic(doc):
    """같은 디렉터리 임시 파일 -> fsync -> chmod -> replace 순서를 유지한다.

    순서가 중요하다. replace 뒤에 chmod를 하면 그 사이에 읽는 쪽이 0600 파일을
    보게 되고, fsync를 빼면 전원이 끊겼을 때 빈 파일이 남는다.
    """
    import inspect

    from src.api import zone_store

    # 파일 전체에서 찾으면 docstring에 쓰인 os.replace를 먼저 집는다.
    # 실제 실행되는 문장만 남기고 본다.
    source = inspect.getsource(zone_store._atomic_write)
    statements = source[source.index("path.parent.mkdir"):]

    calls = ("tempfile.mkstemp", "os.fsync", "os.chmod", "os.replace")
    positions = []
    for call in calls:
        assert call in statements, f"{call}이 _atomic_write에 없습니다"
        assert call in doc, f"{call}이 동결 문서에 없습니다"
        positions.append(statements.index(call))
    assert positions == sorted(positions), f"저장 순서가 바뀌었습니다: {calls}"


def test_polygon_minimum_points_matches_the_freeze(doc):
    from src.geofencing import polygon_rules

    assert polygon_rules.MIN_POLYGON_POINTS == 3
    assert "polygon 최소 점 수" in doc


# --- API 앱 설정 ---


def test_api_app_metadata_matches_the_freeze(doc):
    source = (ROOT / "src" / "api" / "main.py").read_text(encoding="utf-8")
    assert 'title="KidCafe Safety API"' in source
    assert 'version="0.3.0"' in source
    assert "`KidCafe Safety API`" in doc
    assert "`0.3.0`" in doc


def cors_origins() -> list:
    """`add_middleware(CORSMiddleware, allow_origins=[...])`의 실제 목록을 읽는다.

    정규식으로 localhost 패턴만 찾으면 외부 host를 추가해도 검사에 걸리지 않는다.
    origin을 여는 변경이 바로 그 경우라 목록 자체를 파싱한다.
    """
    import ast

    tree = ast.parse((ROOT / "src" / "api" / "main.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "add_middleware"
        ):
            for keyword in node.keywords:
                if keyword.arg == "allow_origins":
                    return ast.literal_eval(keyword.value)
    raise AssertionError("CORS allow_origins를 찾지 못했습니다")


def test_cors_origins_match_the_freeze(doc):
    """origin을 더 열면 문서와 갈린다. 운영 배포는 Phase 4 범위가 아니다."""
    origins = cors_origins()
    assert sorted(origins) == [
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://localhost:5173",
    ], f"허용 origin이 동결과 다릅니다: {origins}"
    for origin in origins:
        assert origin in doc


def test_container_images_and_ports_match_the_freeze(doc):
    api_dockerfile = (ROOT / "Dockerfile.api").read_text(encoding="utf-8")
    frontend_dockerfile = (ROOT / "frontend" / "Dockerfile").read_text(encoding="utf-8")
    assert "FROM python:3.10-slim" in api_dockerfile
    assert "EXPOSE 8000" in api_dockerfile
    assert "EXPOSE 3000" in frontend_dockerfile
    assert "`python:3.10-slim`" in doc
    assert "`8000`" in doc and "`3000`" in doc


# --- 출력 파일 기본값 ---


@pytest.mark.parametrize(
    "option, expected",
    [
        ("--output", "outputs/events.jsonl"),
        ("--csv-output", "outputs/events.csv"),
        ("--summary-output", "outputs/summary.json"),
        ("--overlay-output", "outputs/result.mp4"),
        ("--api-failed-events-output", "outputs/api_failed_events.jsonl"),
        ("--zones", "data/zones/sample.json"),
        ("--infer-device", "auto"),
        ("--log-level", "INFO"),
    ],
)
def test_cli_default_matches_the_freeze(option, expected, doc):
    """제출물의 실행 안내가 실제 기본값과 어긋나지 않게 고정한다."""
    assert cli_defaults().get(option) == expected
    assert f"`{expected}`" in doc


def cli_defaults() -> dict:
    """`src/main.py`의 add_argument 기본값을 소스에서 읽는다."""
    import ast

    tree = ast.parse((ROOT / "src" / "main.py").read_text(encoding="utf-8"))
    defaults = {}
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "add_argument"
            and node.args
            and isinstance(node.args[0], ast.Constant)
        ):
            for keyword in node.keywords:
                if keyword.arg == "default":
                    try:
                        defaults[node.args[0].value] = ast.literal_eval(keyword.value)
                    except ValueError:
                        pass
    return defaults


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
