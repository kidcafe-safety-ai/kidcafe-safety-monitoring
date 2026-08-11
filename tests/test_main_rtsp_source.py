"""main CLI 입력 소스 선택 중 RTSP 경로 테스트."""

from __future__ import annotations

import logging
from argparse import Namespace

import pytest

from src.common.types import Track, Zone, ZoneRules
from src.events.event_manager import EventManager
from src.input.rtsp_source import (
    RTSPCredentialError,
    RTSPFrameMetadata,
    RTSPSource,
    build_rtsp_url,
)
from src.main import _build_source, _resolve_source_frame_number

TEST_RTSP_HOST = "192.0.2.20"
TEST_RTSP_USERNAME = "rtsp-user"
TEST_RTSP_PASSWORD = "rtsp-test-password"


def _rtsp_args(**overrides: object) -> Namespace:
    """_build_source가 참조하는 RTSP 관련 CLI 인자를 만든다."""

    defaults = {
        "source_type": "rtsp",
        "source": None,
        "rtsp_host": TEST_RTSP_HOST,
        "rtsp_port": 554,
        "rtsp_stream": "main",
        "rtsp_path": None,
        "rtsp_alias": "camera_01",
        "rtsp_username_env": "KIDCAFE_RTSP_USERNAME",
        "rtsp_password_env": "KIDCAFE_RTSP_PASSWORD",
        "width": None,
        "height": None,
        "video": "data/videos/test.mp4",
    }
    defaults.update(overrides)
    return Namespace(**defaults)


def test_build_source_rtsp_requires_password_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("KIDCAFE_RTSP_PASSWORD", raising=False)

    with pytest.raises(RTSPCredentialError) as exc_info:
        _build_source(_rtsp_args())

    assert "KIDCAFE_RTSP_PASSWORD" in str(exc_info.value)


def test_build_source_rtsp_from_env_uses_safe_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KIDCAFE_RTSP_USERNAME", TEST_RTSP_USERNAME)
    monkeypatch.setenv("KIDCAFE_RTSP_PASSWORD", TEST_RTSP_PASSWORD)

    source = _build_source(_rtsp_args())

    assert isinstance(source, RTSPSource)
    assert source.source_id == "camera_01"
    assert TEST_RTSP_PASSWORD not in source.source_id


def test_build_source_rtsp_main_stream_path_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KIDCAFE_RTSP_USERNAME", TEST_RTSP_USERNAME)
    monkeypatch.setenv("KIDCAFE_RTSP_PASSWORD", TEST_RTSP_PASSWORD)

    source = _build_source(_rtsp_args(rtsp_alias=None, rtsp_stream="main"))

    assert source.source_id == f"rtsp:{TEST_RTSP_HOST}/media/video1"


def test_build_source_rtsp_sub_stream_path_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KIDCAFE_RTSP_USERNAME", TEST_RTSP_USERNAME)
    monkeypatch.setenv("KIDCAFE_RTSP_PASSWORD", TEST_RTSP_PASSWORD)

    source = _build_source(_rtsp_args(rtsp_alias=None, rtsp_stream="sub"))

    assert source.source_id == f"rtsp:{TEST_RTSP_HOST}/media/video2"


def test_build_source_rtsp_explicit_path_overrides_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KIDCAFE_RTSP_USERNAME", TEST_RTSP_USERNAME)
    monkeypatch.setenv("KIDCAFE_RTSP_PASSWORD", TEST_RTSP_PASSWORD)

    source = _build_source(
        _rtsp_args(rtsp_alias=None, rtsp_stream="main", rtsp_path="/custom/path")
    )

    assert source.source_id == f"rtsp:{TEST_RTSP_HOST}/custom/path"


def test_build_source_rtsp_legacy_url_keeps_sanitized_source_id(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="src.main")
    legacy_url = build_rtsp_url(
        host=TEST_RTSP_HOST,
        username=TEST_RTSP_USERNAME,
        password=TEST_RTSP_PASSWORD,
        path="/media/video1",
    )

    source = _build_source(
        _rtsp_args(
            source=legacy_url,
            rtsp_alias=None,
        )
    )

    assert source.source_id == f"rtsp:{TEST_RTSP_HOST}/media/video1"
    assert TEST_RTSP_PASSWORD not in source.source_id
    assert TEST_RTSP_USERNAME not in caplog.text
    assert TEST_RTSP_PASSWORD not in caplog.text
    assert "rtsp://" not in caplog.text
    assert f"camera_ip={TEST_RTSP_HOST}" in caplog.text
    assert "port=554" in caplog.text
    assert "path=/media/video1" in caplog.text
    assert "username_set=True" in caplog.text
    assert "password_set=True" in caplog.text


def test_rtsp_time_axis_uses_capture_sequence_after_frame_drops() -> None:
    class SourceWithRTSPMetadata:
        def get_last_frame_metadata(self) -> RTSPFrameMetadata:
            return RTSPFrameMetadata(
                capture_sequence=46,
                captured_monotonic=100.0,
                source_elapsed_seconds=3.0,
            )

    fps = 15.0
    processed_frame_number = 15

    source_frame_number = _resolve_source_frame_number(
        SourceWithRTSPMetadata(),
        processed_frame_number=processed_frame_number,
    )

    assert processed_frame_number / fps == pytest.approx(1.0)
    assert source_frame_number == 45
    assert source_frame_number / fps == pytest.approx(3.0)


def test_time_based_zone_rules_use_source_time_after_rtsp_frame_drops() -> None:
    class SourceWithRTSPMetadata:
        def get_last_frame_metadata(self) -> RTSPFrameMetadata:
            return RTSPFrameMetadata(
                capture_sequence=46,
                captured_monotonic=100.0,
                source_elapsed_seconds=3.0,
            )

    fps = 15.0
    zone = Zone(
        zone_id="playground",
        name="Playground",
        type="polygon",
        zone_type="play",
        points=[[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]],
        rules=ZoneRules(enter_alert=True, dwell_threshold_sec=2),
    )
    track = Track(
        track_id=1,
        bbox=[10.0, 10.0, 30.0, 60.0],
        foot_point=[20.0, 60.0],
        confidence=0.9,
    )
    manager = EventManager([zone], fps=fps, enter_confirm_sec=0.0)

    manager.process(
        track=track,
        zones_in=[zone.zone_id],
        frame_number=0,
        video_source="rtsp-test",
    )
    source_frame_number = _resolve_source_frame_number(
        SourceWithRTSPMetadata(),
        processed_frame_number=15,
    )

    events = manager.process(
        track=track,
        zones_in=[zone.zone_id],
        frame_number=source_frame_number,
        video_source="rtsp-test",
    )

    assert 15 / fps == pytest.approx(1.0)
    assert source_frame_number / fps == pytest.approx(3.0)
    assert [event.event_type for event in events] == ["DWELL"]


def test_source_frame_number_falls_back_for_sources_without_metadata() -> None:
    class SourceWithoutRTSPMetadata:
        pass

    assert _resolve_source_frame_number(SourceWithoutRTSPMetadata(), 7) == 7
