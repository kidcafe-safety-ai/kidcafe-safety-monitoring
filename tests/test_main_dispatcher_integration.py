"""main.py의 run_pipeline_from_source가 AsyncEventDispatcher를 올바르게

연결하는지 확인하는 통합 테스트. 실제 모델·영상 없이 PoseTracker 등
무거운 의존성은 mock으로 대체하고, Event/CurrentStatus/Live Frame이
dispatcher로 등록되는지, 종료 시 close()가 호출되는지, api_url이 없을
때 기존 동작(dispatcher 미사용)이 유지되는지 검증한다.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np

import src.main as main_module
from src.common.types import Event
from src.main import run_pipeline_from_source


def _make_mock_source(frame_count: int = 1):
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    source = MagicMock()
    source.fps = 30.0
    source.width = 640
    source.height = 480
    source.total_frames = frame_count
    source.source_id = "test-source"
    source.read.side_effect = [(True, frame)] * frame_count + [(False, None)]
    return source


def _patch_pipeline_internals(fake_events):
    """PoseTracker/zones/EventManager 등 무거운 의존성을 mock으로 교체한다."""
    mock_track = MagicMock(track_id=1, bbox=[10.0, 10.0, 50.0, 50.0])
    mock_tracker = MagicMock()
    mock_tracker.update.return_value = MagicMock(tracks=[mock_track])

    mock_checker = MagicMock()
    mock_checker.check.return_value = []

    mock_event_manager = MagicMock()
    mock_event_manager.process.return_value = fake_events
    mock_event_manager.flush_stale_tracks.return_value = []
    mock_event_manager.get_zone_occupancy.return_value = {}

    mock_writer = MagicMock()
    mock_overlay_writer = MagicMock()

    return patch.multiple(
        main_module,
        ByteTracker=MagicMock(return_value=mock_tracker),
        PoseTracker=MagicMock(return_value=mock_tracker),
        load_zones=MagicMock(return_value=[]),
        ZoneChecker=MagicMock(return_value=mock_checker),
        EventManager=MagicMock(return_value=mock_event_manager),
        EventWriter=MagicMock(return_value=mock_writer),
        VideoOverlayWriter=MagicMock(return_value=mock_overlay_writer),
    ), mock_writer, mock_event_manager


def _make_fake_event() -> Event:
    return Event.create(
        event_type="ENTER",
        track_id=1,
        zone_id="zone_a",
        bbox=[10.0, 10.0, 50.0, 50.0],
        foot_point=[30.0, 50.0],
        frame_number=0,
        video_source="test-source",
    )


class TestDispatcherWiring:
    def test_events_are_enqueued_after_local_write(self):
        fake_event = _make_fake_event()
        patcher, mock_writer, _ = _patch_pipeline_internals([fake_event])
        mock_dispatcher = MagicMock()
        call_order = []
        mock_writer.write_batch.side_effect = lambda *a, **k: call_order.append("write_batch")
        mock_dispatcher.enqueue_event.side_effect = lambda *a, **k: call_order.append(
            "enqueue_event"
        )

        with patcher, patch.object(
            main_module, "AsyncEventDispatcher", return_value=mock_dispatcher
        ) as mock_dispatcher_cls:
            run_pipeline_from_source(
                source=_make_mock_source(),
                zones_path="unused.json",
                api_url="http://localhost:8000",
            )

        mock_dispatcher_cls.assert_called_once()
        _, kwargs = mock_dispatcher_cls.call_args
        assert kwargs["base_url"] == "http://localhost:8000"

        mock_dispatcher.enqueue_event.assert_called_once_with(fake_event)
        # 로컬 EventWriter 저장이 dispatcher 등록보다 먼저 일어나야 한다.
        assert call_order == ["write_batch", "enqueue_event"]

    def test_custom_failed_events_path_is_forwarded(self):
        patcher, _, _ = _patch_pipeline_internals([])
        mock_dispatcher = MagicMock()

        with patcher, patch.object(
            main_module, "AsyncEventDispatcher", return_value=mock_dispatcher
        ) as mock_dispatcher_cls:
            run_pipeline_from_source(
                source=_make_mock_source(),
                zones_path="unused.json",
                api_url="http://localhost:8999",
                api_failed_events_output_path="outputs/run-1-failures.jsonl",
            )

        _, kwargs = mock_dispatcher_cls.call_args
        assert kwargs["failed_events_path"] == "outputs/run-1-failures.jsonl"

    def test_current_status_is_registered_with_dispatcher(self, monkeypatch):
        monkeypatch.setattr(main_module, "_STATUS_UPDATE_INTERVAL_SEC", 0.0)
        patcher, _, _ = _patch_pipeline_internals([])
        mock_dispatcher = MagicMock()

        with patcher, patch.object(
            main_module, "AsyncEventDispatcher", return_value=mock_dispatcher
        ):
            run_pipeline_from_source(
                source=_make_mock_source(),
                zones_path="unused.json",
                api_url="http://localhost:8000",
            )

        mock_dispatcher.update_current_status.assert_called_once()

    def test_live_frame_is_delegated_through_dispatcher(self):
        """LiveFrameClient/LiveFrameDispatcher도 mock 처리해 실제 daemon

        thread·requests.Session이 테스트 중 생성·누수되지 않게 한다.
        """
        patcher, _, _ = _patch_pipeline_internals([])
        mock_dispatcher = MagicMock()
        mock_live_frame_dispatcher = MagicMock()

        with patcher, patch.object(
            main_module, "AsyncEventDispatcher", return_value=mock_dispatcher
        ) as mock_dispatcher_cls, patch.object(
            main_module, "LiveFrameClient", return_value=MagicMock()
        ), patch.object(
            main_module, "LiveFrameDispatcher", return_value=mock_live_frame_dispatcher
        ) as mock_live_frame_dispatcher_cls:
            run_pipeline_from_source(
                source=_make_mock_source(),
                zones_path="unused.json",
                api_url="http://localhost:8000",
                live_frame_enabled=True,
            )

        # LiveFrameDispatcher가 생성되고, 그 인스턴스가 그대로
        # AsyncEventDispatcher(live_frame_dispatcher=...)로 전달됐는지 확인한다.
        mock_live_frame_dispatcher_cls.assert_called_once()
        _, dispatcher_kwargs = mock_dispatcher_cls.call_args
        assert dispatcher_kwargs["live_frame_dispatcher"] is mock_live_frame_dispatcher

        # main.py → dispatcher.update_live_frame() 호출도 검증한다.
        mock_dispatcher.update_live_frame.assert_called_once()
        _, kwargs = mock_dispatcher.update_live_frame.call_args
        assert kwargs["source"] == "test-source"
        assert kwargs["frame_number"] == 0

    def test_dispatcher_close_is_called_on_exit(self):
        patcher, _, _ = _patch_pipeline_internals([])
        mock_dispatcher = MagicMock()

        with patcher, patch.object(
            main_module, "AsyncEventDispatcher", return_value=mock_dispatcher
        ):
            run_pipeline_from_source(
                source=_make_mock_source(),
                zones_path="unused.json",
                api_url="http://localhost:8000",
            )

        mock_dispatcher.close.assert_called_once_with(timeout=3.0)

    def test_dispatcher_close_is_called_even_on_pipeline_error(self):
        patcher, _, mock_event_manager = _patch_pipeline_internals([])
        mock_event_manager.process.side_effect = RuntimeError("boom")
        mock_dispatcher = MagicMock()

        with patcher, patch.object(
            main_module, "AsyncEventDispatcher", return_value=mock_dispatcher
        ):
            try:
                run_pipeline_from_source(
                    source=_make_mock_source(),
                    zones_path="unused.json",
                    api_url="http://localhost:8000",
                )
            except RuntimeError:
                pass

        mock_dispatcher.close.assert_called_once_with(timeout=3.0)

    def test_no_dispatcher_created_when_api_url_is_none(self):
        """api_url=None이면 기존처럼 dispatcher를 아예 만들지 않아야 한다."""
        patcher, _, _ = _patch_pipeline_internals([_make_fake_event()])

        with patcher, patch.object(main_module, "AsyncEventDispatcher") as mock_dispatcher_cls:
            run_pipeline_from_source(
                source=_make_mock_source(),
                zones_path="unused.json",
                api_url=None,
            )

        mock_dispatcher_cls.assert_not_called()
