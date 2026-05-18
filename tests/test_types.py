"""공통 타입 유닛 테스트."""

import pytest

from src.common.types import Event, Track, TrackingResult, Zone


class TestTrack:
    def test_track_creation(self):
        track = Track(
            track_id=1,
            bbox=[100, 150, 200, 350],
            foot_point=[150, 350],
            confidence=0.95,
        )
        assert track.track_id == 1
        assert track.width == 100
        assert track.height == 200
        assert track.area == 20000

    def test_track_validation_confidence(self):
        with pytest.raises(ValueError):
            Track(
                track_id=1,
                bbox=[100, 150, 200, 350],
                foot_point=[150, 350],
                confidence=1.5,
            )

    def test_track_validation_bbox(self):
        with pytest.raises(ValueError):
            Track(
                track_id=1, bbox=[100, 150, 200], foot_point=[150, 350], confidence=0.95
            )


class TestTrackingResult:
    def test_tracking_result_creation(self):
        track = Track(
            track_id=1,
            bbox=[100, 150, 200, 350],
            foot_point=[150, 350],
            confidence=0.95,
        )
        result = TrackingResult(
            frame_number=42,
            timestamp="00:00:01.400",  # 42 frames @ 30fps = 1.4초
            video_source="test.mp4",
            tracks=[track],
        )
        assert result.frame_number == 42
        assert len(result.tracks) == 1


class TestEvent:
    def test_event_create(self):
        event = Event.create(
            event_type="ENTER",
            track_id=1,
            zone_id="danger_door",
            bbox=[100, 150, 200, 350],
            foot_point=[150, 350],
            frame_number=42,
            video_source="test.mp4",
        )
        assert event.event_type == "ENTER"
        assert event.event_id is not None
        assert event.timestamp is not None


class TestZone:
    def test_zone_creation(self):
        zone = Zone(
            zone_id="danger_door",
            name="출입문",
            type="polygon",
            points=[[0.1, 0.2], [0.3, 0.2], [0.3, 0.5], [0.1, 0.5]],
        )
        assert zone.zone_id == "danger_door"
        assert len(zone.points) == 4

    def test_zone_validation_type(self):
        with pytest.raises(ValueError):
            Zone(
                zone_id="test",
                name="test",
                type="invalid_type",
                points=[[0, 0], [1, 0], [1, 1]],
            )
