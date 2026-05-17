"""Events 모듈 테스트 (ENTER + DWELL + EXIT)."""

from src.common.types import Track, Zone, ZoneRules
from src.events.event_manager import EventManager


class TestEventManager:
    def _make_zones(self):
        return [
            Zone(
                zone_id="zone_a",
                name="Test A",
                type="polygon",
                points=[[0.3, 0.4], [0.7, 0.4], [0.7, 0.9], [0.3, 0.9]],
                rules=ZoneRules(enter_alert=True, dwell_threshold_sec=3),
            ),
        ]

    def _make_track(self, track_id=1):
        return Track(
            track_id=track_id,
            bbox=[100, 100, 200, 300],
            foot_point=[150, 300],
            confidence=0.9,
        )

    def test_enter_event(self):
        manager = EventManager(zones=self._make_zones(), fps=30.0)
        events = manager.process(self._make_track(), ["zone_a"], 0, "test.mp4")
        assert len(events) == 1
        assert events[0].event_type == "ENTER"
        assert events[0].timestamp == "00:00:00.000"

    def test_no_duplicate_enter(self):
        manager = EventManager(zones=self._make_zones(), fps=30.0)
        manager.process(self._make_track(), ["zone_a"], 0, "test.mp4")
        events = manager.process(self._make_track(), ["zone_a"], 1, "test.mp4")
        assert events == []

    def test_dwell_event_after_threshold(self):
        """3초 임계, 30fps → 90프레임 후 DWELL 발생."""
        manager = EventManager(zones=self._make_zones(), fps=30.0)
        manager.process(self._make_track(), ["zone_a"], 0, "test.mp4")

        # 89 프레임 (≈2.97초) — 아직 안 발생
        events = manager.process(self._make_track(), ["zone_a"], 89, "test.mp4")
        assert events == []

        # 90 프레임 (3.0초) — 발생
        events = manager.process(self._make_track(), ["zone_a"], 90, "test.mp4")
        assert len(events) == 1
        assert events[0].event_type == "DWELL"

    def test_dwell_only_once(self):
        manager = EventManager(zones=self._make_zones(), fps=30.0)
        manager.process(self._make_track(), ["zone_a"], 0, "test.mp4")
        # 90 프레임에서 DWELL 발생
        manager.process(self._make_track(), ["zone_a"], 90, "test.mp4")
        # 120 프레임 (4초) — 이미 발생했으므로 추가 발생 X
        events = manager.process(self._make_track(), ["zone_a"], 120, "test.mp4")
        assert events == []

    def test_exit_event(self):
        manager = EventManager(zones=self._make_zones(), fps=30.0)
        manager.process(self._make_track(), ["zone_a"], 0, "test.mp4")
        # zone에서 나감
        events = manager.process(self._make_track(), [], 50, "test.mp4")
        assert len(events) == 1
        assert events[0].event_type == "EXIT"

    def test_enter_after_exit(self):
        """나갔다 다시 들어오면 새 ENTER + DWELL 카운트 리셋."""
        manager = EventManager(zones=self._make_zones(), fps=30.0)
        manager.process(self._make_track(), ["zone_a"], 0, "test.mp4")
        manager.process(self._make_track(), [], 50, "test.mp4")  # EXIT

        # 다시 진입
        events = manager.process(self._make_track(), ["zone_a"], 100, "test.mp4")
        assert len(events) == 1
        assert events[0].event_type == "ENTER"
