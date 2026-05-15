"""ByteTracker 모듈 테스트.

YOLO 모델 로드가 필요하므로 시간이 좀 걸림.
"""
import numpy as np

from src.tracking.bytetrack_wrapper import ByteTracker


class TestByteTracker:
    def test_initializes(self):
        tracker = ByteTracker()
        assert tracker.model is not None

    def test_returns_tracking_result_on_black_frame(self):
        """검은 프레임 → 사람 없음 → 빈 tracks."""
        tracker = ByteTracker()
        black_frame = np.zeros((480, 640, 3), dtype=np.uint8)
        result = tracker.update(black_frame, frame_number=0, video_source="test")
        assert result.frame_number == 0
        assert isinstance(result.tracks, list)