"""PoseTracker 모듈 테스트.

YOLO pose 모델 로드가 필요하므로 시간이 좀 걸림.
"""

import numpy as np

from src.tracking.pose_tracker import PoseTracker


class TestPoseTracker:
    def test_initializes(self):
        tracker = PoseTracker()
        assert tracker.model is not None

    def test_returns_tracking_result_on_black_frame(self):
        """검은 프레임 → 사람 없음 → 빈 tracks."""
        tracker = PoseTracker()
        black_frame = np.zeros((480, 640, 3), dtype=np.uint8)
        result = tracker.update(black_frame, frame_number=0, video_source="test")
        assert result.frame_number == 0
        assert isinstance(result.tracks, list)

    def test_reset_clears_bytetrack_state_for_reuse_across_videos(self):
        """ByteTracker.reset()과 동일한 계약: predictor는 유지하고 내부

        BYTETracker 상태만 초기화한다.
        """
        tracker = PoseTracker()
        black_frame = np.zeros((480, 640, 3), dtype=np.uint8)

        tracker.update(black_frame, frame_number=0, video_source="video_a")
        predictor = tracker.model.predictor
        assert predictor is not None

        tracker.reset()
        assert tracker.model.predictor is predictor  # 재사용(재생성 아님)

        result = tracker.update(black_frame, frame_number=0, video_source="video_b")
        assert result.frame_number == 0
        assert isinstance(result.tracks, list)

    def test_reset_does_not_accumulate_tracking_callbacks(self):
        tracker = PoseTracker()
        black_frame = np.zeros((480, 640, 3), dtype=np.uint8)

        def callback_count() -> int:
            return len(tracker.model.callbacks.get("on_predict_postprocess_end", []))

        tracker.update(black_frame, frame_number=0, video_source="video_a")
        baseline = callback_count()

        for i in range(3):
            tracker.reset()
            tracker.update(black_frame, frame_number=0, video_source=f"video_{i}")
            assert callback_count() == baseline
