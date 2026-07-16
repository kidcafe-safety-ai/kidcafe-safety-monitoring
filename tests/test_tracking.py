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

    def test_reset_clears_bytetrack_state_for_reuse_across_videos(self):
        """reset()은 predictor 내부의 BYTETracker 상태(track ID, motion history)를

        초기화해야 한다. 같은 ByteTracker 인스턴스를 여러 영상에 재사용할 때
        (모델 재로딩 비용 절감 목적) reset() 없이는 이전 영상의 추적 이력이
        다음 영상 첫 프레임까지 이어질 수 있다.
        """
        tracker = ByteTracker()
        black_frame = np.zeros((480, 640, 3), dtype=np.uint8)

        tracker.update(black_frame, frame_number=0, video_source="video_a")
        predictor = tracker.model.predictor
        assert predictor is not None  # 첫 update() 후 predictor 생성됨
        bytetracker = predictor.trackers[0]

        calls = []
        original_reset = bytetracker.reset
        bytetracker.reset = lambda: (calls.append(1), original_reset())[-1]

        tracker.reset()

        assert len(calls) == 1  # 내부 BYTETracker.reset()이 호출됨
        assert tracker.model.predictor is predictor  # predictor 자체는 재사용(재생성 아님)

        # reset 이후에도 정상적으로 계속 추적할 수 있어야 한다.
        result = tracker.update(black_frame, frame_number=0, video_source="video_b")
        assert result.frame_number == 0
        assert isinstance(result.tracks, list)

    def test_reset_does_not_accumulate_tracking_callbacks(self):
        """predictor를 None으로 비우던 이전 구현은 reset()마다 ultralytics의

        on_predict_postprocess_end callback을 추가로 등록해, 영상을 거듭할수록
        callback이 중복 실행되는 문제가 있었다. reset()을 여러 번 반복해도
        callback 개수가 늘어나지 않아야 한다.
        """
        tracker = ByteTracker()
        black_frame = np.zeros((480, 640, 3), dtype=np.uint8)

        def callback_count() -> int:
            return len(tracker.model.callbacks.get("on_predict_postprocess_end", []))

        tracker.update(black_frame, frame_number=0, video_source="video_a")
        baseline = callback_count()

        for i in range(3):
            tracker.reset()
            tracker.update(black_frame, frame_number=0, video_source=f"video_{i}")
            assert callback_count() == baseline
