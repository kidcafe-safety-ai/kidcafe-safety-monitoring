"""main.py의 run_pipeline_from_source가 FallPipeline을 올바르게 연결하는지

확인하는 통합 테스트. 실제 모델 로딩 없이 FallPipeline을 mock으로 대체해
(1) fall_detection_enabled=False면 기존처럼 전혀 관여하지 않는지,
(2) True면 매 프레임 process()가 호출되고 반환된 Event가 zone 이벤트와
합쳐져 EventWriter/AsyncEventDispatcher로 흘러가는지,
(3) fall_model_path 지정 여부에 따라 AuxiliaryFallModel 생성 여부가
달라지는지를 검증한다.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

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


def _patch_pipeline_internals(zone_events=None):
    mock_track = MagicMock(track_id=1, bbox=[10.0, 10.0, 50.0, 50.0])
    mock_tracking_result = MagicMock(tracks=[mock_track])
    mock_tracker = MagicMock()
    mock_tracker.update.return_value = mock_tracking_result

    mock_checker = MagicMock()
    mock_checker.check.return_value = []

    mock_event_manager = MagicMock()
    mock_event_manager.process.return_value = zone_events or []
    mock_event_manager.flush_stale_tracks.return_value = []
    mock_event_manager.get_zone_occupancy.return_value = {}

    mock_writer = MagicMock()
    mock_overlay_writer = MagicMock()

    patcher = patch.multiple(
        main_module,
        ByteTracker=MagicMock(return_value=mock_tracker),
        PoseTracker=MagicMock(return_value=mock_tracker),
        load_zones=MagicMock(return_value=[]),
        ZoneChecker=MagicMock(return_value=mock_checker),
        EventManager=MagicMock(return_value=mock_event_manager),
        EventWriter=MagicMock(return_value=mock_writer),
        VideoOverlayWriter=MagicMock(return_value=mock_overlay_writer),
    )
    return patcher, mock_writer, mock_tracking_result


def _make_fall_event() -> Event:
    return Event.create(
        event_type="FALL_SUSPECT",
        track_id=1,
        zone_id=None,
        bbox=[10.0, 10.0, 50.0, 50.0],
        foot_point=[30.0, 50.0],
        frame_number=0,
        video_source="test-source",
    )


class TestFallDetectionDisabledByDefault:
    def test_fall_pipeline_not_constructed_when_disabled(self):
        patcher, _, _ = _patch_pipeline_internals()

        with patcher, patch.object(main_module, "FallPipeline") as mock_fall_pipeline_cls:
            run_pipeline_from_source(
                source=_make_mock_source(),
                zones_path="unused.json",
            )

        mock_fall_pipeline_cls.assert_not_called()


class TestTrackerSelection:
    """낙상 감지를 꺼도 기존처럼 가벼운 ByteTracker+yolo26n.pt를 써야 한다 —

    PoseTracker(yolo26n-pose.pt)는 fall_detection_enabled=True일 때만 선택돼야
    기본 웹캠/Zone 실행이 의도치 않게 더 무거워지지 않는다.
    """

    def test_bytetracker_used_and_default_model_when_fall_detection_disabled(self):
        patcher, _, _ = _patch_pipeline_internals()

        with patcher:
            run_pipeline_from_source(
                source=_make_mock_source(),
                zones_path="unused.json",
                fall_detection_enabled=False,
            )

            main_module.ByteTracker.assert_called_once()
            main_module.PoseTracker.assert_not_called()
            _, kwargs = main_module.ByteTracker.call_args
            assert kwargs["model_path"] == "yolo26n.pt"

    def test_posetracker_used_and_default_model_when_fall_detection_enabled(self):
        patcher, _, _ = _patch_pipeline_internals()

        with patcher, patch.object(
            main_module, "FallPipeline", return_value=MagicMock(process=MagicMock(return_value=[]))
        ):
            run_pipeline_from_source(
                source=_make_mock_source(),
                zones_path="unused.json",
                fall_detection_enabled=True,
            )

            main_module.PoseTracker.assert_called_once()
            main_module.ByteTracker.assert_not_called()
            _, kwargs = main_module.PoseTracker.call_args
            assert kwargs["model_path"] == "yolo26n-pose.pt"

    def test_explicit_model_path_overrides_auto_selection_regardless_of_flag(self):
        patcher, _, _ = _patch_pipeline_internals()

        with patcher:
            run_pipeline_from_source(
                source=_make_mock_source(),
                zones_path="unused.json",
                fall_detection_enabled=False,
                model_path="custom.pt",
            )

            _, kwargs = main_module.ByteTracker.call_args
            assert kwargs["model_path"] == "custom.pt"


class TestFallDetectionEnabled:
    def test_fall_pipeline_process_called_per_frame_and_events_written(self):
        fall_event = _make_fall_event()
        patcher, mock_writer, mock_tracking_result = _patch_pipeline_internals()
        mock_pipeline = MagicMock()
        mock_pipeline.process.return_value = [fall_event]

        with patcher, patch.object(
            main_module, "FallPipeline", return_value=mock_pipeline
        ) as mock_fall_pipeline_cls:
            run_pipeline_from_source(
                source=_make_mock_source(),
                zones_path="unused.json",
                fall_detection_enabled=True,
            )

        mock_fall_pipeline_cls.assert_called_once()
        mock_pipeline.process.assert_called_once()
        args, _ = mock_pipeline.process.call_args
        assert args[1] is mock_tracking_result

        mock_writer.write_batch.assert_called_once()
        (written_events,), _ = mock_writer.write_batch.call_args
        assert fall_event in written_events

    def test_auxiliary_model_created_only_when_fall_model_path_given(self):
        patcher, _, _ = _patch_pipeline_internals()

        with patcher, patch.object(
            main_module, "FallPipeline", return_value=MagicMock(process=MagicMock(return_value=[]))
        ), patch.object(main_module, "AuxiliaryFallModel") as mock_aux_cls:
            run_pipeline_from_source(
                source=_make_mock_source(),
                zones_path="unused.json",
                fall_detection_enabled=True,
                fall_model_path=None,
            )

        mock_aux_cls.assert_not_called()

    def test_auxiliary_model_created_when_fall_model_path_given(self):
        patcher, _, _ = _patch_pipeline_internals()

        with patcher, patch.object(
            main_module, "FallPipeline", return_value=MagicMock(process=MagicMock(return_value=[]))
        ) as mock_fall_pipeline_cls, patch.object(
            main_module, "AuxiliaryFallModel", return_value=MagicMock()
        ) as mock_aux_cls:
            run_pipeline_from_source(
                source=_make_mock_source(),
                zones_path="unused.json",
                fall_detection_enabled=True,
                fall_model_path="outputs/fall_training/models/fall_detector_v1.pt",
                fall_model_conf=0.6,
                fall_model_device="cpu",
            )

        mock_aux_cls.assert_called_once_with(
            model_path="outputs/fall_training/models/fall_detector_v1.pt",
            conf=0.6,
            device="cpu",
        )
        _, kwargs = mock_fall_pipeline_cls.call_args
        assert kwargs["auxiliary_model"] is mock_aux_cls.return_value

    def test_fall_config_path_is_forwarded_to_pipeline(self):
        """cause_attribution 설정(configs/fall_detection.json)이 실제로

        FallPipeline까지 전달되는지 확인한다 — 넘기지 않으면
        FallCauseAttributorConfig가 코드 기본값으로 조용히 대체된다.
        """
        patcher, _, _ = _patch_pipeline_internals()

        with patcher, patch.object(
            main_module, "FallPipeline", return_value=MagicMock(process=MagicMock(return_value=[]))
        ) as mock_fall_pipeline_cls:
            run_pipeline_from_source(
                source=_make_mock_source(),
                zones_path="unused.json",
                fall_detection_enabled=True,
                fall_config_path="configs/fall_detection.json",
            )

        _, kwargs = mock_fall_pipeline_cls.call_args
        assert kwargs["fall_config_path"] == "configs/fall_detection.json"

    def test_fall_model_interval_is_forwarded_to_pipeline(self):
        patcher, _, _ = _patch_pipeline_internals()

        with patcher, patch.object(
            main_module, "FallPipeline", return_value=MagicMock(process=MagicMock(return_value=[]))
        ) as mock_fall_pipeline_cls:
            run_pipeline_from_source(
                source=_make_mock_source(),
                zones_path="unused.json",
                fall_detection_enabled=True,
                fall_model_interval_frames=3,
            )

        _, kwargs = mock_fall_pipeline_cls.call_args
        assert kwargs["auxiliary_inference_interval_frames"] == 3

    def test_pose_normal_gate_is_created_and_forwarded(self):
        patcher, _, _ = _patch_pipeline_internals()
        gate = object()

        with patcher, patch.object(
            main_module, "FallPipeline", return_value=MagicMock(process=MagicMock(return_value=[]))
        ) as mock_fall_pipeline_cls, patch.object(
            main_module, "AuxiliaryFallModel", return_value=MagicMock(enabled=True)
        ), patch.object(main_module, "PoseNormalGate", return_value=gate) as mock_gate:
            run_pipeline_from_source(
                source=_make_mock_source(),
                zones_path="unused.json",
                fall_detection_enabled=True,
                fall_model_path="fall.pt",
                fall_pose_normal_gate_enabled=True,
            )

        mock_gate.assert_called_once()
        _, gate_kwargs = mock_gate.call_args
        assert gate_kwargs["fps"] == 30.0
        assert gate_kwargs["config"].max_aspect_ratio == 0.9
        _, kwargs = mock_fall_pipeline_cls.call_args
        assert kwargs["pose_normal_gate"] is gate

    def test_pose_normal_gate_requires_auxiliary_model_path(self):
        patcher, _, _ = _patch_pipeline_internals()

        with patcher, pytest.raises(ValueError, match="--fall-model-path"):
            run_pipeline_from_source(
                source=_make_mock_source(),
                zones_path="unused.json",
                fall_detection_enabled=True,
                fall_pose_normal_gate_enabled=True,
            )

    def test_zone_and_fall_events_both_flow_to_writer(self):
        from src.common.types import Event as EventType

        zone_event = EventType.create(
            event_type="ENTER",
            track_id=1,
            zone_id="zone_a",
            bbox=[10.0, 10.0, 50.0, 50.0],
            foot_point=[30.0, 50.0],
            frame_number=0,
            video_source="test-source",
        )
        fall_event = _make_fall_event()
        patcher, mock_writer, _ = _patch_pipeline_internals(zone_events=[zone_event])
        mock_pipeline = MagicMock()
        mock_pipeline.process.return_value = [fall_event]

        with patcher, patch.object(main_module, "FallPipeline", return_value=mock_pipeline):
            run_pipeline_from_source(
                source=_make_mock_source(),
                zones_path="unused.json",
                fall_detection_enabled=True,
            )

        (written_events,), _ = mock_writer.write_batch.call_args
        assert zone_event in written_events
        assert fall_event in written_events
