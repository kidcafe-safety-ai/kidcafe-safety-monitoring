"""
시각화 모듈 단위 테스트
실행: pytest tests/test_visualization.py -v
"""
import json
import sys
from pathlib import Path

import pytest

# src 경로 추가
sys.path.insert(0, str(Path(__file__).parent.parent))


# ── 1. 페이지 파일 존재 확인 ──────────────────────────────────────────────────
class TestPageFilesExist:
    VIZ_DIR = Path("src/visualization")

    def test_app_exists(self):
        assert (self.VIZ_DIR / "app.py").exists(), "app.py 없음"

    def test_style_helper_exists(self):
        assert (self.VIZ_DIR / "_style.py").exists(), "_style.py 없음"

    @pytest.mark.parametrize("page", [
        "01_home.py",
        "02_zone_editor.py",
        "03_monitor.py",
        "04_stats_dashboard.py",
        "05_child_report.py",
        "06_settings.py",
    ])
    def test_page_file_exists(self, page):
        assert (self.VIZ_DIR / "pages" / page).exists(), f"{page} 없음"


# ── 2. syntax check ───────────────────────────────────────────────────────────
class TestSyntaxCheck:
    VIZ_DIR = Path("src/visualization")

    def _compile(self, path: Path):
        source = path.read_text(encoding="utf-8")
        compile(source, str(path), "exec")  # SyntaxError 나면 실패

    def test_app_syntax(self):
        self._compile(self.VIZ_DIR / "app.py")

    def test_style_syntax(self):
        self._compile(self.VIZ_DIR / "_style.py")

    @pytest.mark.parametrize("page", [
        "01_home.py",
        "02_zone_editor.py",
        "03_monitor.py",
        "04_stats_dashboard.py",
        "05_child_report.py",
        "06_settings.py",
    ])
    def test_page_syntax(self, page):
        self._compile(self.VIZ_DIR / "pages" / page)


# ── 3. JSONL 파싱 ─────────────────────────────────────────────────────────────
class TestJsonlParsing:
    def _load(self, path: str):
        out = []
        p = Path(path)

        if not p.exists():
            return out

        with open(p, encoding="utf-8") as f:
            for line in f:
                line = line.strip()

                if line:
                    try:
                        out.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass

        return out

    def test_valid_jsonl(self, tmp_path):
        f = tmp_path / "events.jsonl"

        f.write_text(
            '{"event_type":"ENTER","track_id":1,"zone_id":"z1","frame_number":0}\n'
            '{"event_type":"DWELL","track_id":2,"zone_id":"z2","frame_number":10}\n',
            encoding="utf-8",
        )

        events = self._load(str(f))

        assert len(events) == 2
        assert events[0]["event_type"] == "ENTER"
        assert events[1]["track_id"] == 2

    def test_invalid_jsonl_skipped(self, tmp_path):
        """깨진 줄은 건너뛰고 나머지는 파싱."""
        f = tmp_path / "bad.jsonl"

        f.write_text(
            '{"event_type":"ENTER","track_id":1,"zone_id":"z1","frame_number":0}\n'
            'THIS IS NOT JSON\n'
            '{"event_type":"EXIT","track_id":3,"zone_id":"z1","frame_number":99}\n',
            encoding="utf-8",
        )

        events = self._load(str(f))

        assert len(events) == 2
        assert events[1]["event_type"] == "EXIT"

    def test_empty_jsonl(self, tmp_path):
        f = tmp_path / "empty.jsonl"

        f.write_text("", encoding="utf-8")

        events = self._load(str(f))

        assert events == []

    def test_missing_file_returns_empty(self):
        events = self._load("nonexistent/path/events.jsonl")

        assert events == []


# ── 4. Zone JSON 파싱 ─────────────────────────────────────────────────────────
class TestZoneParsing:
    def test_sample_zone_loads(self):
        p = Path("data/zones/sample.json")

        if not p.exists():
            pytest.skip("sample.json 없음")

        with open(p, encoding="utf-8") as f:
            zones = json.load(f)

        assert len(zones) >= 1
        assert "zone_id" in zones[0]
        assert "points" in zones[0]
        assert len(zones[0]["points"]) >= 3

    def test_zone_normalization(self):
        """모든 point 좌표가 0~1 범위인지."""
        p = Path("data/zones/sample.json")

        if not p.exists():
            pytest.skip("sample.json 없음")

        with open(p, encoding="utf-8") as f:
            zones = json.load(f)

        for z in zones:
            for x, y in z["points"]:
                assert 0.0 <= x <= 1.0, f"x 범위 초과: {x}"
                assert 0.0 <= y <= 1.0, f"y 범위 초과: {y}"


# ── 5. _style.py import 및 내용 확인 ─────────────────────────────────────────
class TestStyleModule:
    def test_dark_css_exported(self):
        p = Path("src/visualization/_style.py")

        if not p.exists():
            pytest.skip("_style.py 없음")

        source = p.read_text(encoding="utf-8")

        assert "DARK_CSS" in source
        assert "<style>" in source

    def test_sidebar_status_function_exists(self):
        p = Path("src/visualization/_style.py")

        if not p.exists():
            pytest.skip("_style.py 없음")

        source = p.read_text(encoding="utf-8")

        assert "def sidebar_status" in source