"""PoseTracker 모듈 테스트.

초기화/빈 결과/bbox·keypoint 매핑은 `src.tracking.pose_tracker.YOLO`를
monkeypatch한 fake model로 검증한다(네트워크·모델 캐시 없이 기본 pytest에서
항상 통과). reset()의 predictor/callbacks 처리는 Ultralytics 내부 동작(콜백
누적, tracker 상태 초기화)에 대한 회귀 테스트라 fake로 대체하면 검증 가치가
사라진다 — 이 두 개는 실제 `yolo26n-pose.pt`가 필요한 opt-in integration
test로 남기고, `RUN_MODEL_INTEGRATION=1`일 때만 실행한다:

    RUN_MODEL_INTEGRATION=1 pytest tests/test_pose_tracker.py -m integration
"""

import os

import numpy as np
import pytest

from src.tracking.pose_tracker import PoseTracker


class _FakeTensor:
    """`.cpu().numpy()` 체인만 흉내내는 최소 fake — 실제 torch 텐서 대신 쓴다."""

    def __init__(self, array: np.ndarray):
        self._array = array

    def cpu(self):
        return self

    def numpy(self):
        return self._array


class _FakeBoxes:
    def __init__(self, xyxy, ids, confs):
        self.xyxy = _FakeTensor(np.array(xyxy, dtype=float))
        self.id = None if ids is None else _FakeTensor(np.array(ids, dtype=float))
        self.conf = _FakeTensor(np.array(confs, dtype=float))


class _FakeKeypoints:
    def __init__(self, xy, confs):
        self.xy = _FakeTensor(np.array(xy, dtype=float))
        self.conf = None if confs is None else _FakeTensor(np.array(confs, dtype=float))


class _FakeResult:
    def __init__(self, boxes=None, keypoints=None):
        self.boxes = boxes
        self.keypoints = keypoints


class _FakeYoloModel:
    """PoseTracker가 실제로 쓰는 표면(predict/track)만 구현한다."""

    def __init__(self, track_results_by_call=None):
        self._track_results_by_call = list(track_results_by_call or [])
        self.predict_calls = 0
        self.track_calls = 0

    def predict(self, *args, **kwargs):
        self.predict_calls += 1
        return []

    def track(self, *args, **kwargs):
        self.track_calls += 1
        if self._track_results_by_call:
            return self._track_results_by_call.pop(0)
        return [_FakeResult(boxes=None, keypoints=None)]


def _make_tracker(monkeypatch, track_results_by_call=None) -> PoseTracker:
    fake_model = _FakeYoloModel(track_results_by_call)
    monkeypatch.setattr(
        "src.tracking.pose_tracker.YOLO", lambda model_path: fake_model
    )
    return PoseTracker()


class TestPoseTrackerMocked:
    def test_initializes(self, monkeypatch):
        tracker = _make_tracker(monkeypatch)

        assert tracker.model is not None
        assert tracker.model.predict_calls == 1  # warm-up이 정확히 한 번 호출됨

    def test_returns_tracking_result_on_black_frame(self, monkeypatch):
        """검은 프레임 → 사람 없음(boxes=None) → 빈 tracks."""
        tracker = _make_tracker(monkeypatch)
        black_frame = np.zeros((480, 640, 3), dtype=np.uint8)

        result = tracker.update(black_frame, frame_number=0, video_source="test")

        assert result.frame_number == 0
        assert result.tracks == []

    def test_returns_empty_tracks_when_boxes_have_no_id_yet(self, monkeypatch):
        """탐지는 됐지만 ByteTrack이 아직 ID를 못 준 프레임(예: 첫 프레임)도 빈

        tracks여야 한다 — boxes=None과는 별개 분기(`boxes.id is None`)다.
        """
        fake_result = _FakeResult(
            boxes=_FakeBoxes([[0.0, 0.0, 10.0, 10.0]], ids=None, confs=[0.8]),
            keypoints=None,
        )
        tracker = _make_tracker(monkeypatch, track_results_by_call=[[fake_result]])
        frame = np.zeros((480, 640, 3), dtype=np.uint8)

        result = tracker.update(frame, frame_number=0, video_source="test")

        assert result.tracks == []

    def test_maps_single_person_bbox_and_keypoints_to_track(self, monkeypatch):
        """bbox·track_id·17 keypoint가 Track 필드로 정확히 매핑되는지 검증한다."""
        xyxy = [[10.0, 20.0, 30.0, 60.0]]
        ids = [7]
        confs = [0.91]
        keypoints_xy = [[[float(i), float(i)] for i in range(17)]]
        keypoints_conf = [[0.5] * 17]

        fake_result = _FakeResult(
            boxes=_FakeBoxes(xyxy, ids, confs),
            keypoints=_FakeKeypoints(keypoints_xy, keypoints_conf),
        )
        tracker = _make_tracker(monkeypatch, track_results_by_call=[[fake_result]])
        frame = np.zeros((480, 640, 3), dtype=np.uint8)

        result = tracker.update(frame, frame_number=3, video_source="test")

        assert len(result.tracks) == 1
        track = result.tracks[0]
        assert track.track_id == 7
        assert track.bbox == [10.0, 20.0, 30.0, 60.0]
        assert track.foot_point == [20.0, 60.0]  # [(x1+x2)/2, y2]
        assert track.confidence == pytest.approx(0.91)
        assert len(track.keypoints) == 17
        assert track.keypoints[0] == [0.0, 0.0]
        assert len(track.keypoints_conf) == 17
        assert track.keypoints_conf[0] == pytest.approx(0.5)

    def test_no_keypoints_leaves_track_keypoints_none(self, monkeypatch):
        """result.keypoints가 아예 없으면(pose 없는 모델 등) Track.keypoints도 None이어야 한다."""
        fake_result = _FakeResult(
            boxes=_FakeBoxes([[0.0, 0.0, 10.0, 10.0]], [1], [0.8]),
            keypoints=None,
        )
        tracker = _make_tracker(monkeypatch, track_results_by_call=[[fake_result]])
        frame = np.zeros((480, 640, 3), dtype=np.uint8)

        result = tracker.update(frame, frame_number=0, video_source="test")

        assert result.tracks[0].keypoints is None
        assert result.tracks[0].keypoints_conf is None


_run_integration = os.getenv("RUN_MODEL_INTEGRATION") == "1"


@pytest.mark.integration
@pytest.mark.skipif(
    not _run_integration,
    reason="실제 YOLO pose 모델 통합 테스트는 RUN_MODEL_INTEGRATION=1일 때만 실행합니다.",
)
class TestPoseTrackerRealModelIntegration:
    """실제 yolo26n-pose.pt + Ultralytics 내부(predictor/callbacks) 회귀 테스트.

    reset()이 의존하는 predictor 재사용·트래커 상태 초기화·콜백 누적 방지는
    Ultralytics 라이브러리 내부 동작에 대한 계약이라, fake model로는 검증할
    수 없다 — 실제 모델이 캐시된 환경에서만 의도적으로 실행한다.
    """

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
