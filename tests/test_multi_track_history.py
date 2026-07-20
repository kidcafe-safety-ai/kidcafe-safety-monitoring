"""MultiTrackHistory 단위 테스트."""

from __future__ import annotations

import pytest

from src.common.types import Track, TrackingResult
from src.safety.multi_track_history import MultiTrackHistory


def _make_result(frame_number, video_source="cam1", tracks=None):
    return TrackingResult(
        frame_number=frame_number,
        timestamp="00:00:00.000",
        video_source=video_source,
        tracks=tracks or [],
    )


def _make_track(track_id=1, bbox=None, foot_point=None, confidence=0.9):
    bbox = bbox or [10.0, 10.0, 30.0, 50.0]
    foot_point = foot_point or [20.0, 50.0]
    return Track(track_id=track_id, bbox=bbox, foot_point=foot_point, confidence=confidence)


class TestUpdateAndGetHistory:
    def test_adds_sample_for_seen_track(self):
        history = MultiTrackHistory(fps=10.0)
        history.update(_make_result(0, tracks=[_make_track()]))

        samples = history.get_history("cam1", 1)
        assert len(samples) == 1
        assert samples[0].frame_number == 0
        assert samples[0].time_sec == 0.0
        assert samples[0].bbox == (10.0, 10.0, 30.0, 50.0)

    def test_samples_are_immutable_copies(self):
        history = MultiTrackHistory(fps=10.0)
        track = _make_track()
        history.update(_make_result(0, tracks=[track]))

        track.bbox[0] = 999.0  # 원본을 나중에 mutate해도 저장된 샘플은 영향받지 않아야 함
        samples = history.get_history("cam1", 1)
        assert samples[0].bbox[0] == 10.0

    def test_multiple_frames_accumulate_in_order(self):
        history = MultiTrackHistory(fps=10.0)
        for frame_number in range(5):
            history.update(_make_result(frame_number, tracks=[_make_track()]))

        samples = history.get_history("cam1", 1)
        assert [s.frame_number for s in samples] == [0, 1, 2, 3, 4]


class TestHistoryWindow:
    def test_old_samples_are_trimmed_beyond_window(self):
        fps = 10.0
        history = MultiTrackHistory(fps=fps, history_window_sec=1.0)

        # 0~2초(frame 0~20) 동안 매 frame마다 샘플 추가. window=1.0초이므로
        # 최신 시각 기준 1초를 초과한 샘플은 제거되어야 한다.
        for frame_number in range(21):
            history.update(_make_result(frame_number, tracks=[_make_track()]))

        samples = history.get_history("cam1", 1)
        latest_time = samples[-1].time_sec
        assert all((latest_time - s.time_sec) <= 1.0 for s in samples)
        assert samples[0].frame_number == 10  # 2.0 - 1.0 = 1.0초 시점부터 유지


class TestTrackGracePeriod:
    def test_track_kept_within_grace_period(self):
        fps = 10.0
        history = MultiTrackHistory(fps=fps, track_grace_sec=0.5)
        history.update(_make_result(0, tracks=[_make_track()]))

        # track이 사라진 뒤 0.3초(3 frame)만 지남 → grace period(0.5초) 이내
        history.update(_make_result(3, tracks=[]))

        assert history.get_history("cam1", 1) != []
        assert ("cam1", 1) in history.active_keys()

    def test_track_removed_after_grace_period(self):
        fps = 10.0
        history = MultiTrackHistory(fps=fps, track_grace_sec=0.5)
        history.update(_make_result(0, tracks=[_make_track()]))

        # track이 사라진 뒤 0.6초(6 frame) 지남 → grace period 초과
        history.update(_make_result(6, tracks=[]))

        assert history.get_history("cam1", 1) == []
        assert ("cam1", 1) not in history.active_keys()


class TestVideoSourceIsolation:
    def test_same_track_id_different_video_source_are_independent(self):
        history = MultiTrackHistory(fps=10.0)
        history.update(_make_result(0, video_source="cam1", tracks=[_make_track(track_id=1)]))
        history.update(_make_result(0, video_source="cam2", tracks=[_make_track(track_id=1)]))

        assert len(history.get_history("cam1", 1)) == 1
        assert len(history.get_history("cam2", 1)) == 1
        assert set(history.active_keys()) == {("cam1", 1), ("cam2", 1)}


class TestTrackAgeSec:
    def test_track_age_is_span_between_first_and_last_sample(self):
        fps = 10.0
        history = MultiTrackHistory(fps=fps)
        for frame_number in range(6):  # 0.0 ~ 0.5초
            history.update(_make_result(frame_number, tracks=[_make_track()]))

        assert history.track_age_sec("cam1", 1) == pytest.approx(0.5)

    def test_track_age_is_zero_with_single_sample(self):
        history = MultiTrackHistory(fps=10.0)
        history.update(_make_result(0, tracks=[_make_track()]))

        assert history.track_age_sec("cam1", 1) == 0.0

    def test_track_age_is_zero_for_unknown_track(self):
        history = MultiTrackHistory(fps=10.0)
        assert history.track_age_sec("cam1", 99) == 0.0


class TestInvalidFps:
    def test_rejects_non_positive_fps(self):
        with pytest.raises(ValueError):
            MultiTrackHistory(fps=0)
