"""InputSource 구현체 단위 테스트."""

from __future__ import annotations

import logging
import time
from collections import deque
from urllib.parse import urlsplit

import cv2
import numpy as np
import pytest

from src.input.file_source import FilePlaylistSource, FileVideoSource
from src.input.webcam_source import WebcamSource
from src.input.rtsp_source import (
    RTSPConnectionConfig,
    RTSPCredentialError,
    RTSPSource,
    build_rtsp_url,
    build_rtsp_url_from_env,
    configure_rtsp_tcp_transport,
    normalize_rtsp_env_value,
    sanitize_rtsp_url,
)
from src.input.base import InputSource

TEST_RTSP_HOST = "192.0.2.10"
TEST_RTSP_USERNAME = "rtsp-user"
TEST_RTSP_PASSWORD = "rtsp-test-password"
SPECIAL_RTSP_USERNAME = "rtsp user"
SPECIAL_RTSP_PASSWORD = "pw with symbols:/+"


def _frame(value: int) -> np.ndarray:
    return np.full((2, 2, 3), value, dtype=np.uint8)


class FakeFileCapture:
    def __init__(
        self,
        frames,
        *,
        opened: bool = True,
        fps: float = 30.0,
        width: int = 2,
        height: int = 2,
        rewind_ok: bool = True,
    ) -> None:
        self.frames = list(frames)
        self.opened = opened
        self.fps = fps
        self.width = width
        self.height = height
        self.rewind_ok = rewind_ok
        self.index = 0
        self.released = False

    def isOpened(self):
        return self.opened

    def get(self, prop_id):
        values = {
            cv2.CAP_PROP_FPS: self.fps,
            cv2.CAP_PROP_FRAME_WIDTH: self.width,
            cv2.CAP_PROP_FRAME_HEIGHT: self.height,
            cv2.CAP_PROP_FRAME_COUNT: len(self.frames),
        }
        return values.get(prop_id, 0)

    def set(self, prop_id, value):
        if (
            prop_id == cv2.CAP_PROP_POS_FRAMES
            and value == 0
            and self.rewind_ok
        ):
            self.index = 0
            return True
        return False

    def read(self):
        if self.index >= len(self.frames):
            return False, None
        frame = self.frames[self.index]
        self.index += 1
        return True, frame

    def release(self):
        self.released = True


def _rtsp_test_url(path: str = "/media/video2") -> str:
    return build_rtsp_url(
        host=TEST_RTSP_HOST,
        username=TEST_RTSP_USERNAME,
        password=TEST_RTSP_PASSWORD,
        path=path,
    )


def _wait_until(predicate, timeout_sec: float = 1.0) -> bool:
    deadline = time.perf_counter() + timeout_sec
    while time.perf_counter() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return predicate()


class FakeRTSPCapture:
    """실제 카메라 없이 RTSPSource reader thread를 검증하기 위한 fake capture."""

    def __init__(
        self,
        results,
        *,
        read_delay_sec: float = 0.0,
        repeat_success: bool = False,
    ) -> None:
        self.results = deque(results)
        self.read_delay_sec = read_delay_sec
        self.repeat_success = repeat_success
        self.opened = True
        self.released = False
        self.set_calls = []
        self._next_value = 100

    def isOpened(self):
        return self.opened

    def set(self, prop_id, value):
        self.set_calls.append((prop_id, value))
        return True

    def get(self, prop_id):
        import cv2

        if prop_id == cv2.CAP_PROP_FRAME_WIDTH:
            return 720
        if prop_id == cv2.CAP_PROP_FRAME_HEIGHT:
            return 576
        if prop_id == cv2.CAP_PROP_FPS:
            return 15.0
        return 0

    def getBackendName(self):
        return "FFMPEG"

    def read(self):
        if self.read_delay_sec:
            time.sleep(self.read_delay_sec)
        if self.released:
            return False, None
        if self.results:
            result = self.results.popleft()
            if isinstance(result, Exception):
                raise result
            if result is False:
                return False, None
            return True, result
        if self.repeat_success:
            self._next_value += 1
            return True, _frame(self._next_value)
        time.sleep(0.005)
        return False, None

    def release(self):
        self.released = True
        self.opened = False


class TestInputSourceInterface:
    def test_file_source_is_input_source(self):
        assert issubclass(FileVideoSource, InputSource)

    def test_file_playlist_source_is_input_source(self):
        assert issubclass(FilePlaylistSource, InputSource)

    def test_webcam_source_is_input_source(self):
        assert issubclass(WebcamSource, InputSource)

    def test_rtsp_source_is_input_source(self):
        assert issubclass(RTSPSource, InputSource)


class TestFileVideoSource:
    def test_raises_on_nonexistent_file(self):
        src = FileVideoSource("nonexistent.mp4")
        with pytest.raises(RuntimeError):
            src.open()

    def test_source_id_is_path(self):
        src = FileVideoSource("data/videos/test.mp4")
        assert src.source_id == "data/videos/test.mp4"

    def test_total_frames_available_after_open(self):
        import os
        path = "data/videos/test1.mp4"
        if not os.path.exists(path):
            pytest.skip("테스트 영상 없음")
        src = FileVideoSource(path)
        src.open()
        try:
            assert src.total_frames is None or src.total_frames > 0
            assert src.fps > 0
            assert src.width > 0
            assert src.height > 0
        finally:
            src.release()

    def test_context_manager(self):
        import os
        path = "data/videos/test1.mp4"
        if not os.path.exists(path):
            pytest.skip("테스트 영상 없음")
        with FileVideoSource(path) as src:
            ret, frame = src.read()
            assert ret is True
            assert isinstance(frame, np.ndarray)

    def test_read_returns_false_after_release(self):
        src = FileVideoSource("data/videos/test.mp4")
        # open 없이 read → False 반환 (크래시 없음)
        ret, frame = src.read()
        assert ret is False
        assert frame is None

    def test_rejects_invalid_repeat_count(self):
        with pytest.raises(ValueError, match="repeat_count"):
            FileVideoSource("demo.mp4", repeat_count=0)

    def test_repeats_file_and_reports_total_frames(self, monkeypatch):
        capture = FakeFileCapture([_frame(1), _frame(2)])
        monkeypatch.setattr(
            "src.input.file_source.cv2.VideoCapture", lambda _: capture
        )
        source = FileVideoSource("demo.mp4", repeat_count=2)
        source.open()

        values = []
        while True:
            ret, frame = source.read()
            if not ret:
                break
            values.append(int(frame[0, 0, 0]))

        assert values == [1, 2, 1, 2]
        assert source.cycle_index == 1
        assert source.total_frames == 4

    def test_repeat_fails_clearly_when_backend_cannot_rewind(self, monkeypatch):
        capture = FakeFileCapture([_frame(1)], rewind_ok=False)
        monkeypatch.setattr(
            "src.input.file_source.cv2.VideoCapture", lambda _: capture
        )
        source = FileVideoSource("demo.mp4", repeat_count=2)
        source.open()
        assert source.read()[0] is True

        with pytest.raises(RuntimeError, match="되감을 수 없습니다"):
            source.read()


class TestFilePlaylistSource:
    def test_rejects_empty_playlist_and_invalid_repeat_count(self):
        with pytest.raises(ValueError, match="paths"):
            FilePlaylistSource([])
        with pytest.raises(ValueError, match="repeat_count"):
            FilePlaylistSource(["first.mp4"], repeat_count=0)

    def test_plays_files_in_order_and_repeats_playlist(self, monkeypatch):
        def capture_factory(path):
            value = 1 if path == "first.mp4" else 2
            return FakeFileCapture([_frame(value)])

        monkeypatch.setattr(
            "src.input.file_source.cv2.VideoCapture", capture_factory
        )
        source = FilePlaylistSource(
            ["first.mp4", "second.mp4"], repeat_count=2
        )
        source.open()

        values = []
        source_ids = []
        while True:
            ret, frame = source.read()
            if not ret:
                break
            values.append(int(frame[0, 0, 0]))
            source_ids.append(source.source_id)

        assert values == [1, 2, 1, 2]
        assert source_ids == [
            "first.mp4",
            "second.mp4",
            "first.mp4",
            "second.mp4",
        ]
        assert source.cycle_index == 3

    def test_rejects_unopenable_file_before_playback(self, monkeypatch):
        captures = {
            "first.mp4": FakeFileCapture([_frame(1)]),
            "missing.mp4": FakeFileCapture([], opened=False),
        }
        monkeypatch.setattr(
            "src.input.file_source.cv2.VideoCapture", captures.__getitem__
        )
        source = FilePlaylistSource(["first.mp4", "missing.mp4"])

        with pytest.raises(RuntimeError, match="missing.mp4"):
            source.open()
        assert captures["first.mp4"].released is True
        assert captures["missing.mp4"].released is True

    @pytest.mark.parametrize(
        "second_kwargs",
        [{"fps": 25.0}, {"width": 4}, {"height": 4}],
    )
    def test_rejects_format_change_before_playback(
        self, monkeypatch, second_kwargs
    ):
        captures = {
            "first.mp4": FakeFileCapture([_frame(1)]),
            "second.mp4": FakeFileCapture([_frame(2)], **second_kwargs),
        }
        monkeypatch.setattr(
            "src.input.file_source.cv2.VideoCapture", captures.__getitem__
        )
        source = FilePlaylistSource(["first.mp4", "second.mp4"])

        with pytest.raises(ValueError, match="형식이 첫 파일과 다릅니다"):
            source.open()
        assert captures["first.mp4"].released is True
        assert captures["second.mp4"].released is True


class TestWebcamSource:
    def test_source_id_format(self):
        src = WebcamSource(device=0)
        assert src.source_id == "webcam:0"

    def test_fps_fallback_when_not_opened(self):
        src = WebcamSource(device=0)
        # open 전이므로 기본 fallback 값
        assert src.fps == 30.0

    def test_fps_override(self):
        src = WebcamSource(device=0, fps_override=15.0)
        assert src.fps == 15.0

    def test_total_frames_is_none(self):
        src = WebcamSource(device=0)
        assert src.total_frames is None

    def test_read_returns_false_before_open(self):
        src = WebcamSource(device=0)
        ret, frame = src.read()
        assert ret is False
        assert frame is None

    def test_raises_on_invalid_device(self):
        src = WebcamSource(device=999)
        with pytest.raises(RuntimeError):
            src.open()


class TestRTSPSource:
    def test_source_id_is_safe_rtsp_identifier(self):
        src = RTSPSource("rtsp://example.com/stream")
        assert src.source_id == "rtsp:example.com/stream"

    def test_source_id_uses_alias_when_provided(self):
        src = RTSPSource(_rtsp_test_url("/stream"), alias="camera_01")
        assert src.source_id == "camera_01"

    def test_source_id_does_not_expose_password_without_alias(self):
        src = RTSPSource(_rtsp_test_url("/stream"), alias=None)
        assert src.source_id == f"rtsp:{TEST_RTSP_HOST}/stream"
        assert TEST_RTSP_PASSWORD not in src.source_id

    def test_total_frames_is_none(self):
        src = RTSPSource("rtsp://example.com/stream")
        assert src.total_frames is None

    def test_read_returns_false_before_open(self):
        src = RTSPSource("rtsp://example.com/stream")
        ret, frame = src.read()
        assert ret is False
        assert frame is None

    def test_build_rtsp_url_encodes_special_characters(self):
        url = build_rtsp_url(
            host="192.168.0.4",
            username=SPECIAL_RTSP_USERNAME,
            password=SPECIAL_RTSP_PASSWORD,
            path="/media/video1",
        )

        assert "rtsp%20user" in url
        assert "pw%20with%20symbols%3A%2F%2B" in url
        assert SPECIAL_RTSP_USERNAME not in url
        assert SPECIAL_RTSP_PASSWORD not in url
        assert url.endswith("@192.168.0.4:554/media/video1")

    def test_build_rtsp_url_from_env_requires_password(self, monkeypatch):
        monkeypatch.delenv("KIDCAFE_RTSP_PASSWORD", raising=False)

        with pytest.raises(RTSPCredentialError) as exc_info:
            build_rtsp_url_from_env(RTSPConnectionConfig(host="192.168.0.4"))

        assert "KIDCAFE_RTSP_PASSWORD" in str(exc_info.value)

    def test_build_rtsp_url_from_env_uses_username_and_password_env(self, monkeypatch):
        monkeypatch.setenv("KIDCAFE_RTSP_USERNAME", TEST_RTSP_USERNAME)
        monkeypatch.setenv("KIDCAFE_RTSP_PASSWORD", SPECIAL_RTSP_PASSWORD)

        url = build_rtsp_url_from_env(
            RTSPConnectionConfig(host="192.168.0.4", path="/media/video1")
        )

        parsed = urlsplit(url)
        assert parsed.hostname == "192.168.0.4"
        assert parsed.path == "/media/video1"
        assert TEST_RTSP_USERNAME in url
        assert "pw%20with%20symbols%3A%2F%2B" in url
        assert SPECIAL_RTSP_PASSWORD not in url

    def test_normalize_rtsp_env_value_trims_outer_quotes_and_whitespace(self):
        assert normalize_rtsp_env_value(' "wrapped value" \r\n') == "wrapped value"
        assert normalize_rtsp_env_value(" 'rtsp-user' ") == "rtsp-user"
        assert normalize_rtsp_env_value("internal space") == "internal space"

    def test_build_rtsp_url_from_env_normalizes_wrapped_env_values(self, monkeypatch):
        monkeypatch.setenv("KIDCAFE_RTSP_USERNAME", ' "rtsp-user" ')
        monkeypatch.setenv("KIDCAFE_RTSP_PASSWORD", ' "wrapped value" \r\n')

        url = build_rtsp_url_from_env(
            RTSPConnectionConfig(host="192.168.0.4", path="/media/video1")
        )

        assert "rtsp-user" in url
        assert "wrapped%20value" in url
        assert "%22" not in url
        assert "%0D" not in url
        assert "%0A" not in url

    def test_sanitize_rtsp_url_masks_password(self):
        safe_url = sanitize_rtsp_url(_rtsp_test_url("/media/video1"))

        assert safe_url == f"rtsp://***:***@{TEST_RTSP_HOST}:554/media/video1"
        assert TEST_RTSP_USERNAME not in safe_url
        assert TEST_RTSP_PASSWORD not in safe_url

    def test_from_env_source_id_does_not_expose_credential(self, monkeypatch):
        monkeypatch.setenv("KIDCAFE_RTSP_USERNAME", TEST_RTSP_USERNAME)
        monkeypatch.setenv("KIDCAFE_RTSP_PASSWORD", TEST_RTSP_PASSWORD)

        src = RTSPSource.from_env(
            RTSPConnectionConfig(host="192.168.0.4", path="/media/video1")
        )

        assert src.source_id == "rtsp:192.168.0.4/media/video1"
        assert TEST_RTSP_PASSWORD not in src.source_id

    def test_configure_rtsp_tcp_transport_sets_opencv_option(self, monkeypatch):
        monkeypatch.delenv("OPENCV_FFMPEG_CAPTURE_OPTIONS", raising=False)

        configure_rtsp_tcp_transport()

        import os

        assert "rtsp_transport;tcp" in os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"]

    def test_open_failure_message_does_not_expose_password(self, monkeypatch, caplog):
        class FakeCapture:
            def isOpened(self):
                return False

            def set(self, *_args):
                return True

            def release(self):
                pass

        caplog.set_level(logging.INFO, logger="src.input.rtsp_source")
        monkeypatch.setattr(
            "src.input.rtsp_source.cv2.VideoCapture",
            lambda *_args, **_kwargs: FakeCapture(),
        )
        src = RTSPSource(_rtsp_test_url("/media/video1"))

        with pytest.raises(RuntimeError) as exc_info:
            src.open()

        assert TEST_RTSP_PASSWORD not in str(exc_info.value)
        assert TEST_RTSP_USERNAME not in caplog.text
        assert TEST_RTSP_PASSWORD not in caplog.text
        assert "rtsp://" not in caplog.text
        assert "비밀번호" in str(exc_info.value)
        assert TEST_RTSP_HOST in str(exc_info.value)
        assert "username_set=True" in caplog.text
        assert "password_set=True" in caplog.text
        assert "requested_backend=CAP_FFMPEG" in caplog.text
        assert "isOpened=False" in caplog.text

    def test_open_attempts_capture_buffer_size_one(self, monkeypatch):
        import cv2

        fake_capture = FakeRTSPCapture([_frame(1)], read_delay_sec=0.005)
        monkeypatch.setattr(
            "src.input.rtsp_source.cv2.VideoCapture",
            lambda *_args, **_kwargs: fake_capture,
        )
        src = RTSPSource(
            _rtsp_test_url(),
            read_wait_sec=0.005,
            stale_timeout_sec=0.2,
        )

        try:
            src.open()
            assert (cv2.CAP_PROP_BUFFERSIZE, 1) in fake_capture.set_calls
        finally:
            src.release()

    def test_latest_frame_only_when_producer_is_faster_than_consumer(self, monkeypatch):
        fake_capture = FakeRTSPCapture([_frame(i) for i in range(1, 6)])
        monkeypatch.setattr(
            "src.input.rtsp_source.cv2.VideoCapture",
            lambda *_args, **_kwargs: fake_capture,
        )
        src = RTSPSource(
            _rtsp_test_url(),
            read_wait_sec=0.005,
            stale_timeout_sec=0.2,
        )

        try:
            src.open()
            assert _wait_until(lambda: src.get_stats().captured_frames >= 5)

            ret, frame = src.read()
            stats = src.get_stats()

            assert ret is True
            assert frame is not None
            assert int(frame[0, 0, 0]) == 5
            assert stats.captured_frames >= 5
            assert stats.delivered_frames == 1
            assert stats.dropped_frames >= 4
            assert isinstance(src._latest_frame, np.ndarray)
        finally:
            src.release()

    def test_delivered_frame_metadata_preserves_capture_sequence_after_drops(
        self,
        monkeypatch,
    ):
        fake_capture = FakeRTSPCapture([_frame(i) for i in range(1, 6)])
        monkeypatch.setattr(
            "src.input.rtsp_source.cv2.VideoCapture",
            lambda *_args, **_kwargs: fake_capture,
        )
        src = RTSPSource(
            _rtsp_test_url(),
            read_wait_sec=0.005,
            stale_timeout_sec=0.2,
        )

        try:
            src.open()
            assert _wait_until(lambda: src.get_stats().captured_frames >= 5)

            ret, frame = src.read()
            metadata = src.get_last_frame_metadata()
            stats = src.get_stats()

            assert ret is True
            assert frame is not None
            assert metadata is not None
            assert int(frame[0, 0, 0]) == 5
            assert metadata.capture_sequence == stats.captured_frames
            assert metadata.capture_sequence > stats.delivered_frames
            assert stats.dropped_frames >= 4
        finally:
            src.release()

    def test_dropped_frames_increase_when_latest_frame_is_overwritten(self, monkeypatch):
        fake_capture = FakeRTSPCapture([_frame(1), _frame(2), _frame(3)])
        monkeypatch.setattr(
            "src.input.rtsp_source.cv2.VideoCapture",
            lambda *_args, **_kwargs: fake_capture,
        )
        src = RTSPSource(
            _rtsp_test_url(),
            read_wait_sec=0.005,
            stale_timeout_sec=0.2,
        )

        try:
            src.open()
            assert _wait_until(lambda: src.get_stats().captured_frames >= 3)

            stats = src.get_stats()

            assert stats.dropped_frames >= 2
        finally:
            src.release()

    def test_read_does_not_return_same_frame_twice(self, monkeypatch):
        fake_capture = FakeRTSPCapture([_frame(9)])
        monkeypatch.setattr(
            "src.input.rtsp_source.cv2.VideoCapture",
            lambda *_args, **_kwargs: fake_capture,
        )
        src = RTSPSource(
            _rtsp_test_url(),
            read_wait_sec=0.005,
            stale_timeout_sec=0.05,
            max_consecutive_read_failures=5,
        )

        try:
            src.open()
            assert _wait_until(lambda: src.get_stats().captured_frames == 1)

            first_ret, first_frame = src.read()
            second_ret, second_frame = src.read()

            assert first_ret is True
            assert first_frame is not None
            assert int(first_frame[0, 0, 0]) == 9
            assert second_ret is False
            assert second_frame is None
            assert src.get_stats().delivered_frames == 1
        finally:
            src.release()

    def test_single_read_failure_does_not_stop_stream(self, monkeypatch):
        fake_capture = FakeRTSPCapture([False, _frame(7)], read_delay_sec=0.002)
        monkeypatch.setattr(
            "src.input.rtsp_source.cv2.VideoCapture",
            lambda *_args, **_kwargs: fake_capture,
        )
        src = RTSPSource(
            _rtsp_test_url(),
            read_wait_sec=0.005,
            stale_timeout_sec=0.2,
        )

        try:
            src.open()
            ret, frame = src.read()
            stats = src.get_stats()

            assert ret is True
            assert frame is not None
            assert int(frame[0, 0, 0]) == 7
            assert stats.read_failures >= 1
            assert stats.delivered_frames == 1
        finally:
            src.release()

    def test_consecutive_read_failures_stop_stream_after_threshold(self, monkeypatch):
        fake_capture = FakeRTSPCapture([False, False, False, False])
        monkeypatch.setattr(
            "src.input.rtsp_source.cv2.VideoCapture",
            lambda *_args, **_kwargs: fake_capture,
        )
        src = RTSPSource(
            _rtsp_test_url(),
            read_wait_sec=0.005,
            stale_timeout_sec=1.0,
            max_consecutive_read_failures=3,
        )

        try:
            src.open()
            ret, frame = src.read()
            stats = src.get_stats()

            assert ret is False
            assert frame is None
            assert stats.read_failures >= 3
            assert stats.consecutive_read_failures >= 3
        finally:
            src.release()

    def test_release_stops_reader_thread(self, monkeypatch):
        fake_capture = FakeRTSPCapture([], read_delay_sec=0.002, repeat_success=True)
        monkeypatch.setattr(
            "src.input.rtsp_source.cv2.VideoCapture",
            lambda *_args, **_kwargs: fake_capture,
        )
        src = RTSPSource(
            _rtsp_test_url(),
            read_wait_sec=0.005,
            stale_timeout_sec=0.2,
        )

        src.open()
        assert _wait_until(lambda: src.get_stats().captured_frames > 0)
        thread = src._reader_thread

        src.release()

        assert fake_capture.released is True
        assert thread is not None
        assert thread.is_alive() is False

    def test_capture_thread_exception_marks_terminal_without_credential_log(
        self,
        monkeypatch,
        caplog,
    ):
        fake_capture = FakeRTSPCapture([RuntimeError("decoder failed")])
        monkeypatch.setattr(
            "src.input.rtsp_source.cv2.VideoCapture",
            lambda *_args, **_kwargs: fake_capture,
        )
        caplog.set_level(logging.ERROR, logger="src.input.rtsp_source")
        src = RTSPSource(
            _rtsp_test_url(),
            read_wait_sec=0.005,
            stale_timeout_sec=0.2,
        )

        try:
            src.open()
            ret, frame = src.read()

            assert ret is False
            assert frame is None
            assert _wait_until(
                lambda: "exception_type=RuntimeError" in caplog.text
            )
            assert TEST_RTSP_PASSWORD not in caplog.text
            assert TEST_RTSP_USERNAME not in caplog.text
            assert "rtsp://" not in caplog.text
        finally:
            src.release()
