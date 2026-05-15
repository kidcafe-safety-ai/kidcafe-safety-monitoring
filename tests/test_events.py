"""Events 모듈 테스트."""
from src.common.types import Track
from src.events.event_manager import EventManager


class TestEventManager:
    def _make_track(self, track_id=1):
        return Track(
            track_id=track_id,
            bbox=[100, 100, 200, 300],
            foot_point=[150, 300],
            confidence=0.9,
        )

    def test_enter_event_on_first_entry(self):
        manager = EventManager()
        track = self._make_track()
        events = manager.process(track, ["zone_a"], 0, "test.mp4")
        assert len(events) == 1
        assert events[0].event_type == "ENTER"

    def test_no_duplicate_enter(self):
        manager = EventManager()
        track = self._make_track()
        manager.process(track, ["zone_a"], 0, "test.mp4")
        events = manager.process(track, ["zone_a"], 1, "test.mp4")
        assert events == []

    def test_enter_different_zones(self):
        manager = EventManager()
        track = self._make_track()
        events = manager.process(track, ["zone_a", "zone_b"], 0, "test.mp4")
        assert len(events) == 2