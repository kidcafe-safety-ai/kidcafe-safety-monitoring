"""`scripts/cache_zone_foot_points.py`의 입력 검증과 파일 출력 검증.

tracking 자체는 모델과 영상이 있어야 돌므로 여기서 검사하지 않는다. 대신
**조용히 잘못될 수 있는 부분**을 본다. manifest와 다른 영상을 넣으면 ground
truth의 frame 번호가 다른 시점을 가리키는데 결과 수치는 그럴듯하게 나온다.
그런 입력이 추론 단계까지 가지 못하게 막는 것이 이 검증의 목적이다.

`ByteTracker`는 import 시점에 모델을 로드하지 않으므로 이 모듈은 ultralytics
없이도 import된다. tracking을 실제로 부르는 경로만 피하면 된다.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

czf = pytest.importorskip(
    "scripts.cache_zone_foot_points",
    reason="cv2 또는 tracking 의존성이 없으면 건너뛴다",
)

EXPECTED = {"fps": 59.94006, "frame_count": 506, "width": 1920, "height": 1080}


# --- 영상 속성 검증 ---


def test_matching_properties_pass():
    czf.verify_video_properties("v.mp4", 1920, 1080, 59.94006, EXPECTED)


def test_wrong_resolution_is_rejected():
    with pytest.raises(czf.CacheError, match="해상도"):
        czf.verify_video_properties("v.mp4", 1280, 720, 59.94006, EXPECTED)


def test_half_frame_rate_is_rejected():
    """카톡 재인코딩본(29.97fps)을 원본 대신 넣으면 frame 번호가 2배 어긋난다."""
    with pytest.raises(czf.CacheError, match="fps"):
        czf.verify_video_properties("v.mp4", 1920, 1080, 29.97003, EXPECTED)


def test_container_jitter_within_tolerance_passes():
    """컨테이너가 적는 fps는 소수점 아래가 조금 흔들린다. 그건 통과시킨다."""
    czf.verify_video_properties("v.mp4", 1920, 1080, 59.9401, EXPECTED)


def test_frame_count_mismatch_is_rejected():
    with pytest.raises(czf.CacheError, match="frame 수"):
        czf.verify_frame_count("v.mp4", 400, EXPECTED)


def test_frame_count_match_passes():
    czf.verify_frame_count("v.mp4", 506, EXPECTED)


# --- manifest 읽기 ---


def write_manifest(path: Path, rows, header=None):
    header = header or list(czf.MANIFEST_FIELDS)
    with open(path, "w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)
    return path


def sample_rows():
    return [
        ["V1", "data/videos/a.mp4", 59.94006, 506, 1920, 1080],
        ["V2", "data/videos/b.mp4", 59.94006, 526, 1920, 1080],
    ]


def test_manifest_is_read(tmp_path):
    path = write_manifest(tmp_path / "m.csv", sample_rows())
    assert [r["video_id"] for r in czf.load_manifest(path, None)] == ["V1", "V2"]


def test_video_id_filter_selects_a_subset(tmp_path):
    path = write_manifest(tmp_path / "m.csv", sample_rows())
    assert [r["video_id"] for r in czf.load_manifest(path, ["V2"])] == ["V2"]


def test_unknown_video_id_is_rejected(tmp_path):
    """오타로 아무 영상도 안 도는 상태를 성공으로 보이게 두지 않는다."""
    path = write_manifest(tmp_path / "m.csv", sample_rows())
    with pytest.raises(czf.CacheError, match="V9"):
        czf.load_manifest(path, ["V9"])


def test_missing_field_is_rejected(tmp_path):
    path = write_manifest(
        tmp_path / "m.csv",
        [["V1", "data/videos/a.mp4", 59.94006, 506]],
        header=["video_id", "video_path", "fps", "frame_count"],
    )
    with pytest.raises(czf.CacheError, match="필드"):
        czf.load_manifest(path, None)


def test_missing_manifest_is_rejected(tmp_path):
    with pytest.raises(czf.CacheError, match="manifest"):
        czf.load_manifest(tmp_path / "nope.csv", None)


def test_empty_manifest_is_rejected(tmp_path):
    path = write_manifest(tmp_path / "m.csv", [])
    with pytest.raises(czf.CacheError, match="처리할 영상"):
        czf.load_manifest(path, None)


# --- 출력 ---


def test_checksum_matches_hashlib(tmp_path):
    import hashlib

    target = tmp_path / "blob.bin"
    target.write_bytes(b"kidcafe" * 1000)
    assert czf.sha256_file(target) == hashlib.sha256(target.read_bytes()).hexdigest()


def test_cache_json_is_written_and_readable(tmp_path):
    target = tmp_path / "nested" / "cache.json"
    payload = {"schema_version": czf.CACHE_SCHEMA_VERSION, "videos": {}}
    czf.write_json_atomic(target, payload)
    assert json.loads(target.read_text(encoding="utf-8")) == payload
    assert not list(target.parent.glob("*.tmp"))


def test_written_bytes_use_lf_on_every_platform(tmp_path):
    """Windows 텍스트 모드는 \\n을 \\r\\n으로 바꾼다.

    실제로 Windows에서 만든 결과 JSON이 전 줄 CRLF로 나왔다. 커밋되는
    artifact라 OS마다 바이트가 달라지면 안 되고, 저장소는 이미 CRLF 유입으로
    `git diff --check`가 걸린 적이 있다. 그래서 바이너리로 쓴다.
    """
    target = tmp_path / "cache.json"
    czf.write_json_atomic(target, {"videos": {}, "note": "한글"})
    raw = target.read_bytes()
    assert b"\r\n" not in raw
    assert raw.endswith(b"\n")


def test_cache_schema_matches_the_evaluator(tmp_path):
    """캐시를 만드는 쪽과 읽는 쪽의 schema 이름이 갈리면 안 된다."""
    from scripts import evaluate_zone_paths as ezp

    assert czf.CACHE_SCHEMA_VERSION == ezp.CACHE_SCHEMA_VERSION


# --- tracker 호출부 ---
#
# tracking 경로는 torch가 있어야 실행되므로 위 테스트들이 지나가지 않는다.
# 그래서 `ByteTracker(...)` 인자 이름이 틀려도 영상을 넣고 돌리기 전에는
# 드러나지 않았다(실제로 `confidence=`로 썼다가 실행 시점에 TypeError가 났다).
# 아래 두 검사는 소스를 파싱해 호출부와 시그니처를 대조하므로 torch 없이도
# 같은 종류의 실수를 잡는다.


def tracker_init_params():
    """`ByteTracker.__init__`이 받는 인자 이름을 소스에서 읽는다."""
    import ast

    source = ROOT / "src" / "tracking" / "bytetrack_wrapper.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "ByteTracker":
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == "__init__":
                    return {a.arg for a in item.args.args} - {"self"}
    raise AssertionError("ByteTracker.__init__을 찾지 못했습니다")


def tracker_call_keywords():
    """`cache_zone_foot_points.py`가 `ByteTracker(...)`에 넘기는 키워드."""
    import ast

    tree = ast.parse((ROOT / "scripts" / "cache_zone_foot_points.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "ByteTracker"
        ):
            return {kw.arg for kw in node.keywords}
    raise AssertionError("ByteTracker 호출을 찾지 못했습니다")


def test_tracker_is_called_with_arguments_it_accepts():
    unknown = tracker_call_keywords() - tracker_init_params()
    assert not unknown, f"ByteTracker가 받지 않는 인자: {sorted(unknown)}"


def test_confidence_is_actually_passed_to_the_tracker():
    """--confidence를 넘겨도 tracker에 닿지 않으면 조용히 기본값으로 돈다."""
    assert "conf" in tracker_call_keywords()
