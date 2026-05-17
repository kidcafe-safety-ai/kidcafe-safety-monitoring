"""video_overlay 모듈 테스트."""
import os
import numpy as np
import pytest

from src.common.types import Event, Track, Zone, ZoneRules
from src.visualization.video_overlay import VideoOverlayWriter, get_event_color


class TestVideoOverlayWriter:
    def test_writes_mp4(self, tmp_path):
        out = tmp_path / "test_overlay.mp4"
        writer = VideoOverlayWriter(str(out), 640, 480, 30.0)

        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        track = Track(track_id=1, bbox=[100, 100, 200, 300],
                      foot_point=[150, 300], confidence=0.9)
        zone = Zone(zone_id="z", name="Test", type="polygon",
                    points=[[0.1, 0.1], [0.5, 0.1], [0.5, 0.5], [0.1, 0.5]])

        for _ in range(10):
            writer.write_frame(frame, [track], [zone], [])
        writer.close()

        assert out.exists()
        assert out.stat().st_size > 0


class TestEventColor:
    def test_known_colors(self):
        assert get_event_color("ENTER") != get_event_color("DWELL")
        assert get_event_color("DWELL") != get_event_color("EXIT")

    def test_unknown_color(self):
        # 알 수 없는 이벤트는 기본 색상
        assert get_event_color("UNKNOWN") is not None