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


# 문서 표에서 값을 직접 읽는다.
#
# 처음에는 상수 **이름**이 문서에 있는지만 봤다. 그러면 문서의 값을 3.0에서
# 9.0으로 바꿔도 테스트가 통과한다. "문서와 코드 중 한쪽만 바꾸면 CI가
# 실패한다"는 이 파일의 목적이 성립하지 않는 상태였다.
#
# 문서 표는 전부 `| 이름 | `값` | ...` 형태이므로 두 번째 칸을 파싱해 코드값과
# 직접 대조한다. 이름은 상수처럼 backtick이 붙은 것도, `dwell threshold 상한`
# 처럼 산문인 것도 있어 양쪽을 받는다.
_DOC_ROW = r"^\|\s*`?{name}`?\s*\|\s*`([^`]+)`"


def documented_value(doc: str, name: str) -> str:
    """동결 문서 표에서 `name` 행의 값 칸을 읽는다.

    행이 없으면 실패한다. 상수를 코드에서 지웠는데 문서에는 남아 있거나 그
    반대인 경우를 조용히 넘기지 않기 위해서다.
    """
    pattern = re.compile(_DOC_ROW.format(name=re.escape(name)), re.MULTILINE)
    matches = pattern.findall(doc)
    if not matches:
        raise AssertionError(f"동결 문서 표에 `{name}` 행이 없습니다")
    if len(set(matches)) > 1:
        raise AssertionError(f"동결 문서에 `{name}` 값이 여러 개입니다: {sorted(set(matches))}")
    return matches[0]


def assert_documented(doc: str, name: str, value) -> None:
    """코드값과 문서에 적힌 값이 같은지 본다.

    문서는 `25.0`처럼 문자열로 적히므로 같은 방식으로 문자열을 만들어 비교한다.
    float은 `25.0`과 `25`를 같게 보되, 그 외에는 표기까지 정확히 맞춘다.
    """
    documented = documented_value(doc, name)
    if isinstance(value, bool) or not isinstance(value, float):
        assert str(value) == documented, (
            f"{name}: 코드 {value!r}와 문서 {documented!r}가 다릅니다"
        )
        return
    try:
        parsed = float(documented)
    except ValueError:
        raise AssertionError(f"{name}: 문서 값 {documented!r}을 수로 읽을 수 없습니다")
    assert parsed == value, f"{name}: 코드 {value!r}와 문서 {documented!r}가 다릅니다"


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
    assert_documented(doc, name, expected)


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
    assert_documented(doc, name, expected)


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
    assert_documented(doc, name, expected)


def test_failed_event_path_matches_the_freeze(doc):
    """API가 죽어도 Event를 잃지 않는다는 계약의 저장 위치다."""
    from src.integrations import async_event_dispatcher

    path = async_event_dispatcher._DEFAULT_FAILED_EVENTS_PATH
    assert path == "outputs/api_failed_events.jsonl"
    assert_documented(doc, "_DEFAULT_FAILED_EVENTS_PATH", path)


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


def test_live_frame_documented_values_match_the_client(doc):
    """해상도와 품질은 상수 이름이 아니라 항목 이름으로 적혀 있다."""
    from src.integrations import live_frame_client

    assert_documented(
        doc, "_DEFAULT_MIN_INTERVAL_SEC", live_frame_client._DEFAULT_MIN_INTERVAL_SEC
    )
    assert_documented(doc, "--live-frame-quality", live_frame_client._DEFAULT_QUALITY)

    resolution = re.search(r"^\|\s*전송 해상도\s*\|\s*`(\d+)`\s*×\s*`(\d+)`", doc, re.MULTILINE)
    assert resolution, "동결 문서에 전송 해상도 행이 없습니다"
    assert int(resolution.group(1)) == live_frame_client._TARGET_WIDTH
    assert int(resolution.group(2)) == live_frame_client._TARGET_HEIGHT


def test_live_frame_stale_timeout_matches_the_freeze(doc):
    """stale이면 204다. 빈 이미지를 만들어 내려주지 않는다."""
    from src.api import live_frame_store

    assert live_frame_store.DEFAULT_STALE_AFTER_SEC == 3.0
    assert_documented(doc, "DEFAULT_STALE_AFTER_SEC", 3.0)


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
    assert_documented(doc, "DEFAULT_RTSP_HOST", rtsp_source.DEFAULT_RTSP_HOST)
    assert_documented(doc, "DEFAULT_RTSP_PORT", rtsp_source.DEFAULT_RTSP_PORT)
    assert "덮어써야" in doc


# --- Zone 저장 계약 ---


def test_zone_store_constants_match_the_freeze(doc):
    from src.api import zone_store

    assert zone_store.VERSION_PREFIX == "sha256:"
    assert zone_store.MAX_DWELL_THRESHOLD_SEC == 3600
    assert zone_store.NORMALIZED_RANGE == (0.0, 1.0)
    assert zone_store.DEFAULT_RUNTIME_FILE_MODE == 0o644
    assert documented_value(doc, "dwell threshold 상한") == "3600"
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


# --- 이 파일 자체가 동결을 지키는지 ---


def test_a_changed_document_value_is_caught(doc):
    """문서 값만 바꾸면 실패해야 한다.

    처음 판에서는 상수 이름이 문서에 있는지만 봤다. 그래서 `3.0`을 `9.0`으로
    바꾼 문서도 그대로 통과했고, "한쪽만 고치면 CI가 걸린다"는 이 파일의 전제가
    성립하지 않았다. 그 상태로 되돌아가면 이 테스트가 먼저 걸린다.
    """
    from src.input import rtsp_source

    tampered = doc.replace(
        "| `_RTSP_STALE_TIMEOUT_SEC` | `3.0` |",
        "| `_RTSP_STALE_TIMEOUT_SEC` | `9.0` |",
    )
    assert tampered != doc, "문서에서 대조 대상 행을 찾지 못했습니다"

    with pytest.raises(AssertionError, match="다릅니다"):
        assert_documented(
            tampered, "_RTSP_STALE_TIMEOUT_SEC", rtsp_source._RTSP_STALE_TIMEOUT_SEC
        )


def test_a_missing_document_row_is_caught(doc):
    """문서에서 행을 지워도 조용히 넘어가면 안 된다."""
    with pytest.raises(AssertionError, match="없습니다"):
        documented_value(doc, "_THIS_CONSTANT_DOES_NOT_EXIST")


# --- DB schema 동결 (현수 2번) ---


def _documented_columns(doc: str, table: str) -> list:
    """문서의 `**\\`table\\`** ... — a, b, c` 줄에서 컬럼 이름을 뽑는다."""
    match = re.search(
        rf"^\*\*`{table}`\*\*[^—]*—(.+?)(?=\n\n)", doc, re.MULTILINE | re.DOTALL
    )
    assert match, f"동결 문서에 {table} 컬럼 목록이 없습니다"
    return re.findall(r"`([A-Za-z_][A-Za-z0-9_]*)`", match.group(1))


def _actual_columns(table: str) -> list:
    """실제로 만들어지는 schema를 그대로 읽는다.

    문서가 CREATE TABLE만 보고 쓰이면 migration으로 붙는 컬럼을 빠뜨린다.
    실제로 `event_confidence`·`cause_json`이 그렇게 빠져 있었다. 그래서 임시
    DB를 만들어 `PRAGMA table_info`로 최종 schema를 읽는다.
    """
    import importlib
    import os
    import sqlite3
    import tempfile

    from src.api import database

    with tempfile.TemporaryDirectory() as directory:
        db_path = Path(directory) / "freeze_check.db"
        previous = os.environ.get("KIDCAFE_DB_PATH")
        os.environ["KIDCAFE_DB_PATH"] = str(db_path)
        try:
            importlib.reload(database)
            database.init_db()
            with sqlite3.connect(db_path) as connection:
                rows = connection.execute(f"PRAGMA table_info({table})").fetchall()
        finally:
            if previous is None:
                os.environ.pop("KIDCAFE_DB_PATH", None)
            else:
                os.environ["KIDCAFE_DB_PATH"] = previous
            importlib.reload(database)
    return [row[1] for row in rows]


@pytest.mark.parametrize("table", ["events", "current_status"])
def test_documented_columns_match_the_real_schema(table, doc):
    """문서의 컬럼 목록이 실제 최종 schema와 같아야 한다.

    "DB 컬럼을 동결했다"고 적어두고 목록이 실제와 다르면 동결이 아니다.
    """
    assert _documented_columns(doc, table) == _actual_columns(table)


def test_phase_3_columns_are_in_the_final_schema(doc):
    """migration으로 붙는 컬럼도 동결 대상이다."""
    from src.api import database

    columns = _actual_columns("events")
    for column in database._EVENTS_PHASE_3_COLUMNS:
        assert column in columns, f"{column}이 실제 schema에 없습니다"
        assert f"`{column}`" in doc, f"{column}이 동결 문서에 없습니다"


# --- 12절 실행 명령이 실제 코드 경로와 맞는지 ---


@pytest.fixture(scope="module")
def run_section(doc) -> str:
    match = re.search(r"^## 12\. 실행 명령\n(.*?)^---$", doc, re.MULTILINE | re.DOTALL)
    assert match, "동결 문서에 12절이 없습니다"
    return match.group(1)


@pytest.fixture(scope="module")
def run_commands(run_section) -> list:
    """12절의 bash 블록만 뽑는다.

    산문에서 옵션 이름을 언급하는 것과 실제 명령에 그 옵션이 있는 것은 다르다.
    본문 전체를 문자열로 훑으면 "`--fall-detection-enabled`가 기본 비활성이라"
    같은 설명 문장에 걸려 명령이 비어 있어도 통과한다.
    """
    blocks = re.findall(r"```bash\n(.*?)```", run_section, re.DOTALL)
    assert blocks, "12절에 실행 명령 블록이 없습니다"
    return blocks


def vision_ai_commands(blocks: list) -> list:
    """`python -m src.main ...` 한 덩어리씩 끊는다."""
    commands = []
    for block in blocks:
        for chunk in re.split(r"\n(?=python )", block):
            if "src.main" in chunk or "src/main.py" in chunk:
                commands.append(chunk)
    assert commands, "12절에 Vision AI 실행 명령이 없습니다"
    return commands


def test_rtsp_command_does_not_bypass_credential_assembly(run_commands):
    """완성된 URL을 --source로 넘기면 환경변수 인증정보가 쓰이지 않는다.

    `_build_source()`는 --source가 rtsp://로 시작하면 RTSPSource(url=...)를
    직접 만들고 RTSPSource.from_env()를 타지 않는다. 그러면 바로 위에서 export한
    KIDCAFE_RTSP_USERNAME·PASSWORD가 URL 조립에 쓰이지 않아, 문서 명령대로
    실행해도 인증이 붙지 않는다.
    """
    main_source = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
    assert 'startswith("rtsp://")' in main_source, "우회 분기가 사라졌으면 이 테스트를 고친다"

    for command in vision_ai_commands(run_commands):
        if "--source-type rtsp" not in command:
            continue
        assert "rtsp://" not in command, f"URL을 직접 넘기는 명령이 있습니다:\n{command}"
        assert "--rtsp-host" in command, f"--rtsp-host가 빠진 명령이 있습니다:\n{command}"


def test_every_rtsp_command_uses_the_recommended_sub_stream(run_commands, run_section):
    """실시간 AI 권장은 sub stream인데 CLI 기본값은 main이다.

    명령이 여러 개이므로 하나만 확인하면 안 된다. RTSP 명령 전부를 본다.
    """
    from src.input import rtsp_source

    assert rtsp_source.DEFAULT_RTSP_SUB_PATH == "/media/video2"
    assert rtsp_source.DEFAULT_RTSP_MAIN_PATH == "/media/video1"

    rtsp_commands = [
        c for c in vision_ai_commands(run_commands) if "--source-type rtsp" in c
    ]
    assert rtsp_commands, "12절에 RTSP 실행 명령이 없습니다"
    for command in rtsp_commands:
        assert "--rtsp-stream sub" in command, f"sub stream이 빠진 명령이 있습니다:\n{command}"
    assert "/media/video2" in run_section


def test_run_commands_use_one_invocation_style(run_commands):
    """제출용 기준 명령은 한쪽으로 통일한다."""
    for command in vision_ai_commands(run_commands):
        assert command.startswith("python -m src.main"), (
            f"실행 방식이 통일되지 않았습니다:\n{command}"
        )


def test_docker_start_includes_zone_runtime_init(run_section):
    """runtime Zone 파일은 Git에 없고 API가 자동 생성하지 않는다.

    초기화를 건너뛰면 새 clone에서 GET /zones가 500을 준다.
    """
    assert (ROOT / "scripts" / "init_zone_runtime.py").is_file()

    init_at = run_section.find("python scripts/init_zone_runtime.py")
    compose_at = run_section.find("docker compose up --build")
    assert init_at != -1, "12절에 Zone runtime 초기화 단계가 없습니다"
    assert compose_at != -1
    assert init_at < compose_at, "초기화가 docker compose 뒤에 있습니다"


def test_zone_runtime_file_is_not_tracked_by_git():
    """문서가 초기화 단계를 요구하는 근거다. 커밋되면 그 전제가 깨진다."""
    import subprocess

    tracked = subprocess.run(
        ["git", "ls-files", "outputs/zones_runtime.json"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert tracked == "", "zones_runtime.json이 커밋되어 있습니다"


def test_api_does_not_create_a_missing_zone_runtime_file():
    """GET /zones는 누락된 파일을 만들어주지 않고 실패한다."""
    import inspect

    from src.api import zone_store

    source = inspect.getsource(zone_store._read_runtime)
    assert "if not path.is_file():" in source
    assert "ZoneConfigUnavailableError" in source
    # 자동 생성 경로(ensure_runtime_file)를 읽기 경로가 부르지 않는다.
    assert "ensure_runtime_file" not in source


def test_final_e2e_command_enables_fall_detection(run_commands, run_section):
    """낙상은 기본 비활성이라 명시하지 않으면 FALL_SUSPECT를 검증하지 못한다."""
    main_source = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
    assert "fall_detection_enabled=False" in main_source

    enabled = [
        c for c in vision_ai_commands(run_commands) if "--fall-detection-enabled" in c
    ]
    assert enabled, "12절 실행 명령 중 낙상을 켜는 것이 없습니다"
    assert "최종 E2E" in run_section
