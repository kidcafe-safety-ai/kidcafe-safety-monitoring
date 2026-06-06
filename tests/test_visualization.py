"""Visualization and Phase 1.5 React Dashboard structure tests."""

import json
import re
import sys
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).parent.parent))


class TestReactDashboardFilesExist:
    FRONTEND_DIR = Path("frontend")
    SRC_DIR = FRONTEND_DIR / "src"

    @pytest.mark.parametrize(
        "path",
        [
            FRONTEND_DIR / "package.json",
            FRONTEND_DIR / "index.html",
            FRONTEND_DIR / "vite.config.ts",
            SRC_DIR / "main.tsx",
            SRC_DIR / "App.tsx",
            SRC_DIR / "App.css",
            SRC_DIR / "pages" / "MonitoringPage.tsx",
            SRC_DIR / "pages" / "EventsPage.tsx",
            SRC_DIR / "api" / "eventsApi.ts",
            SRC_DIR / "types" / "event.ts",
            SRC_DIR / "mocks" / "mockEvents.ts",
            SRC_DIR / "mocks" / "mockSummary.ts",
            SRC_DIR / "mocks" / "mockZoneStatus.ts",
        ],
    )
    def test_react_dashboard_file_exists(self, path):
        assert path.exists(), f"{path} not found"


class TestReactDashboardApiContract:
    def test_events_api_uses_contract_wrapper(self):
        source = Path("frontend/src/api/eventsApi.ts").read_text(encoding="utf-8")

        assert 'status: "success"' in source
        assert "data," in source
        assert "message: null" in source
        assert "ApiResponse" in source

    @pytest.mark.parametrize(
        "path",
        [
            Path("frontend/src/pages/MonitoringPage.tsx"),
            Path("frontend/src/pages/EventsPage.tsx"),
            Path("frontend/src/components/RecentEventList.tsx"),
            Path("frontend/src/components/EventTable.tsx"),
            Path("frontend/src/components/EventChart.tsx"),
            Path("frontend/src/components/ZoneStatusPanel.tsx"),
        ],
    )
    def test_pages_and_components_do_not_import_mocks_directly(self, path):
        source = path.read_text(encoding="utf-8")

        assert "../mocks" not in source
        assert "mocks/" not in source

    def test_mock_event_timestamps_match_backend_contract(self):
        source = Path("frontend/src/mocks/mockEvents.ts").read_text(encoding="utf-8")
        timestamps = re.findall(r'timestamp:\s*"([^"]+)"', source)

        assert timestamps
        for timestamp in timestamps:
            assert re.fullmatch(r"\d{2}:\d{2}:\d{2}\.\d{3}", timestamp), timestamp


class TestJsonlParsing:
    def _load(self, path: str):
        out = []
        p = Path(path)

        if not p.exists():
            return out

        with open(p, encoding="utf-8") as file:
            for line in file:
                line = line.strip()

                if line:
                    try:
                        out.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass

        return out

    def test_valid_jsonl(self, tmp_path):
        events_file = tmp_path / "events.jsonl"

        events_file.write_text(
            '{"event_type":"ENTER","track_id":1,"zone_id":"z1","frame_number":0}\n'
            '{"event_type":"DWELL","track_id":2,"zone_id":"z2","frame_number":10}\n',
            encoding="utf-8",
        )

        events = self._load(str(events_file))

        assert len(events) == 2
        assert events[0]["event_type"] == "ENTER"
        assert events[1]["track_id"] == 2

    def test_invalid_jsonl_skipped(self, tmp_path):
        events_file = tmp_path / "bad.jsonl"

        events_file.write_text(
            '{"event_type":"ENTER","track_id":1,"zone_id":"z1","frame_number":0}\n'
            "THIS IS NOT JSON\n"
            '{"event_type":"EXIT","track_id":3,"zone_id":"z1","frame_number":99}\n',
            encoding="utf-8",
        )

        events = self._load(str(events_file))

        assert len(events) == 2
        assert events[1]["event_type"] == "EXIT"

    def test_empty_jsonl(self, tmp_path):
        events_file = tmp_path / "empty.jsonl"

        events_file.write_text("", encoding="utf-8")

        events = self._load(str(events_file))

        assert events == []

    def test_missing_file_returns_empty(self):
        events = self._load("nonexistent/path/events.jsonl")

        assert events == []


class TestZoneParsing:
    def test_sample_zone_loads(self):
        zones_path = Path("data/zones/sample.json")

        if not zones_path.exists():
            pytest.skip("sample.json not found")

        with open(zones_path, encoding="utf-8") as file:
            zones = json.load(file)

        assert len(zones) >= 1
        assert "zone_id" in zones[0]
        assert "points" in zones[0]
        assert len(zones[0]["points"]) >= 3

    def test_zone_normalization(self):
        zones_path = Path("data/zones/sample.json")

        if not zones_path.exists():
            pytest.skip("sample.json not found")

        with open(zones_path, encoding="utf-8") as file:
            zones = json.load(file)

        for zone in zones:
            for x, y in zone["points"]:
                assert 0.0 <= x <= 1.0, f"x out of range: {x}"
                assert 0.0 <= y <= 1.0, f"y out of range: {y}"
