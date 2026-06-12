"""InputSource 구현체 단위 테스트."""

from __future__ import annotations

import numpy as np
import pytest

from src.input.file_source import FileVideoSource
from src.input.webcam_source import WebcamSource
from src.input.rtsp_source import RTSPSource
from src.input.base import InputSource


class TestInputSourceInterface:
    def test_file_source_is_input_source(self):
        assert issubclass(FileVideoSource, InputSource)

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
    def test_source_id_is_url(self):
        src = RTSPSource("rtsp://example.com/stream")
        assert src.source_id == "rtsp://example.com/stream"

    def test_source_id_uses_alias_when_provided(self):
        src = RTSPSource("rtsp://user:pass@192.168.1.1/stream", alias="camera_01")
        assert src.source_id == "camera_01"

    def test_source_id_falls_back_to_url_without_alias(self):
        src = RTSPSource("rtsp://example.com/stream", alias=None)
        assert src.source_id == "rtsp://example.com/stream"

    def test_total_frames_is_none(self):
        src = RTSPSource("rtsp://example.com/stream")
        assert src.total_frames is None

    def test_read_returns_false_before_open(self):
        src = RTSPSource("rtsp://example.com/stream")
        ret, frame = src.read()
        assert ret is False
        assert frame is None

    def test_raises_on_invalid_url(self):
        src = RTSPSource("rtsp://invalid-host-that-does-not-exist/stream")
        with pytest.raises(RuntimeError):
            src.open()
