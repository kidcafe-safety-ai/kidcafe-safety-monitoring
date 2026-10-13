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
from src.common.types import Event, Zone
from src.main import _build_current_status, run_pipeline_from_source


def _make_mock_source(frame_count: int = 1):
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    source = MagicMock()
    source.fps = 30.0
    source.width = 640
    source.height = 480
    source.total_frames = frame_count
    source.source_id = "test-source"
    source.cycle_index = 0
    source.read.side_effect = [(True, frame)] * frame_count + [(False, None)]
    return source


def _make_switching_source():
    """두 파일 경계를 한 번 통과하는 가벼운 입력 소스를 만든다."""
    frame = np.zeros((480, 640, 3), dtype=np.uint8)

    class SwitchingSource:
        fps = 30.0
        width = 640
        height = 480
        total_frames = 2

        def __init__(self):
            self.index = 0
            self.cycle_index = 0

        @property
        def source_id(self):
            return "first.mp4" if self.cycle_index == 0 else "second.mp4"

        def open(self):
            pass

        def read(self):
            if self.index >= 2:
                return False, None
            if self.index == 1:
                self.cycle_index = 1
            self.index += 1
            return True, frame

        def release(self):
            pass

    return SwitchingSource()


def _patch_pipeline_internals(fake_events, zones=None):
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
        load_zones=MagicMock(return_value=zones or []),
        ZoneChecker=MagicMock(return_value=mock_checker),
        EventManager=MagicMock(return_value=mock_event_manager),
        AuxiliaryFallModel=MagicMock(return_value=MagicMock(enabled=True)),
        FallDetectorConfig=MagicMock(),
        FallPipeline=MagicMock(return_value=MagicMock()),
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


def _danger_zone() -> Zone:
    return Zone(
        zone_id="danger_floor",
        name="위험 구역",
        type="polygon",
        zone_type="danger",
        points=[[0.1, 0.1], [0.5, 0.1], [0.5, 0.5]],
    )


def test_current_status_keeps_all_configured_zones_and_applies_risk_policy():
    play_zone = Zone(
        zone_id="play_floor",
        name="놀이 구역",
        type="polygon",
        zone_type="play",
        points=[[0.1, 0.1], [0.5, 0.1], [0.5, 0.5]],
    )
    empty_danger_zone = Zone(
        zone_id="empty_danger_floor",
        name="비어 있는 위험 구역",
        type="polygon",
        zone_type="danger",
        points=[[0.2, 0.2], [0.3, 0.2], [0.3, 0.3]],
    )
    status = _build_current_status(
        source_id="camera-1",
        frame_number=10,
        active_track_count=2,
        zone_occupancy={"play_floor": 1, "danger_floor": 1},
        zones=[play_zone, _danger_zone(), empty_danger_zone],
    )

    assert status["zone_occupancy"] == [
        {
            "zone_id": "play_floor",
            "zone_name": "놀이 구역",
            "current_count": 1,
            "risk_level": "NORMAL",
        },
        {
            "zone_id": "danger_floor",
            "zone_name": "위험 구역",
            "current_count": 1,
            "risk_level": "HIGH",
        },
        {
            "zone_id": "empty_danger_floor",
            "zone_name": "비어 있는 위험 구역",
            "current_count": 0,
            "risk_level": "NORMAL",
        },
    ]


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

    def test_current_status_is_registered_with_dispatcher(self):
        patcher, _, _ = _patch_pipeline_internals([])
        mock_dispatcher = MagicMock()

        with patcher, patch.object(
            main_module, "AsyncEventDispatcher", return_value=mock_dispatcher
        ):
            run_pipeline_from_source(
                source=_make_mock_source(),
                zones_path="unused.json",
                api_url="http://localhost:8000",
                status_update_interval_sec=0.01,
            )

        assert mock_dispatcher.update_current_status.call_count == 2

    def test_final_status_clears_people_and_configured_zones(self):
        patcher, _, _ = _patch_pipeline_internals([], zones=[_danger_zone()])
        mock_dispatcher = MagicMock()

        with patcher, patch.object(
            main_module, "AsyncEventDispatcher", return_value=mock_dispatcher
        ):
            run_pipeline_from_source(
                source=_make_mock_source(),
                zones_path="unused.json",
                api_url="http://localhost:8000",
            )

        final_status = mock_dispatcher.update_current_status.call_args_list[-1].args[0]
        assert final_status["active_track_count"] == 0
        assert final_status["zone_occupancy"] == [
            {
                "zone_id": "danger_floor",
                "zone_name": "위험 구역",
                "current_count": 0,
                "risk_level": "NORMAL",
            }
        ]

    def test_file_boundary_resets_state_without_reloading_model(self):
        patcher, _, _ = _patch_pipeline_internals([])
        with patcher:
            run_pipeline_from_source(
                source=_make_switching_source(),
                zones_path="unused.json",
                fall_detection_enabled=True,
                fall_model_path="fall.pt",
            )

            main_module.ByteTracker.assert_not_called()
            main_module.PoseTracker.assert_called_once()
            main_module.PoseTracker.return_value.reset.assert_called_once()
            assert main_module.EventManager.call_count == 2
            main_module.AuxiliaryFallModel.assert_called_once()
            assert main_module.FallPipeline.call_count == 2

    def test_file_boundary_resets_state_when_fall_detection_is_disabled(self):
        patcher, _, _ = _patch_pipeline_internals([])
        with patcher:
            run_pipeline_from_source(
                source=_make_switching_source(),
                zones_path="unused.json",
                fall_detection_enabled=False,
            )

            main_module.ByteTracker.assert_called_once()
            main_module.ByteTracker.return_value.reset.assert_called_once()
            main_module.PoseTracker.assert_not_called()
            assert main_module.EventManager.call_count == 2
            main_module.AuxiliaryFallModel.assert_not_called()
            main_module.FallPipeline.assert_not_called()

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
