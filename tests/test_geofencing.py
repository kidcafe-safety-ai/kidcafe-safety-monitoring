"""Geofencing 모듈 테스트."""
from src.common.types import Track, Zone
from src.geofencing.zone_checker import ZoneChecker
from src.geofencing.zone_loader import load_zones


class TestZoneLoader:
    def test_load_sample(self):
        zones = load_zones("data/zones/sample.json")
        assert len(zones) >= 1


class TestZoneChecker:
    def _make_zone(self):
        return Zone(
            zone_id="test_zone",
            name="test",
            type="polygon",
            points=[[0.3, 0.4], [0.7, 0.4], [0.7, 0.9], [0.3, 0.9]],
        )

    def test_inside_zone(self):
        zone = self._make_zone()
        checker = ZoneChecker([zone], frame_width=1000, frame_height=1000)
        track = Track(
            track_id=1,
            bbox=[480, 500, 520, 600],
            foot_point=[500, 600],
            confidence=0.9,
        )
        assert "test_zone" in checker.check(track)

    def test_outside_zone(self):
        zone = self._make_zone()
        checker = ZoneChecker([zone], frame_width=1000, frame_height=1000)
        track = Track(
            track_id=1,
            bbox=[80, 50, 120, 100],
            foot_point=[100, 100],
            confidence=0.9,
        )
        assert checker.check(track) == []

    def test_on_boundary_counts_as_inside(self):
        """covers()는 경계 위도 inside."""
        zone = self._make_zone()
        checker = ZoneChecker([zone], frame_width=1000, frame_height=1000)
        track = Track(
            track_id=1,
            bbox=[280, 400, 320, 500],
            foot_point=[300, 500],
            confidence=0.9,
        )
        assert "test_zone" in checker.check(track)