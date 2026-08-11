"""Runtime metrics output and CLI wiring tests."""

from __future__ import annotations

import hashlib
import json
import sys
from unittest.mock import MagicMock, patch

import numpy as np

import src.main as main_module
from src.main import run_pipeline_from_source


def _make_mock_source(frame_count: int):
    frame = np.zeros((32, 32, 3), dtype=np.uint8)
    source = MagicMock()
    source.fps = 30.0
    source.width = 32
    source.height = 32
    source.total_frames = frame_count
    source.source_id = "metrics-test"
    source.read.side_effect = [(True, frame)] * frame_count + [(False, None)]
    return source


def _patch_pipeline_internals():
    tracker = MagicMock()
    tracker.update.return_value = MagicMock(tracks=[])
    event_manager = MagicMock()
    event_manager.flush_stale_tracks.return_value = []
    event_manager.get_zone_occupancy.return_value = {}
    return patch.multiple(
        main_module,
        ByteTracker=MagicMock(return_value=tracker),
        load_zones=MagicMock(return_value=[]),
        ZoneChecker=MagicMock(return_value=MagicMock()),
        EventManager=MagicMock(return_value=event_manager),
        EventWriter=MagicMock(return_value=MagicMock()),
        VideoOverlayWriter=MagicMock(return_value=MagicMock()),
    )


def test_pipeline_writes_frame_loop_metrics(tmp_path):
    output_path = tmp_path / "metrics.json"

    with _patch_pipeline_internals():
        run_pipeline_from_source(
            source=_make_mock_source(frame_count=2),
            zones_path="unused.json",
            metrics_output_path=str(output_path),
        )

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["processed_frames"] == 2
    assert payload["warmup_frames"] == 30
    assert payload["warmup_frames_excluded"] == 2
    assert payload["avg_fps"] > 0
    assert payload["steady_state"]["processed_frames"] == 0


def test_cli_forwards_metrics_and_failure_paths(monkeypatch, tmp_path):
    source = MagicMock()
    fall_model_path = tmp_path / "fall_model.pt"
    fall_model_path.touch()
    selected_model = tmp_path / "selected.pt"
    selected_model.write_bytes(b"selected-model")
    profile_path = tmp_path / "fall_e1_selected.json"
    profile_path.write_text(
        json.dumps(
            {
                "schema_version": "phase4_fall_e1_freeze_v1",
                "status": "selected_for_phase4_target_domain",
                "default_enabled": True,
                "integrity_policy": "sha256_fail_closed_before_input_open",
                "model": {
                    "path": str(selected_model),
                    "sha256": hashlib.sha256(
                        selected_model.read_bytes()
                    ).hexdigest(),
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "src.main",
            "--metrics-output",
            "outputs/run/metrics.json",
            "--api-failed-events-output",
            "outputs/run/failures.jsonl",
            "--fall-profile",
            str(profile_path),
            "--fall-model-interval-frames",
            "3",
            "--fall-model-path",
            str(fall_model_path),
            "--fall-model-sha256",
            hashlib.sha256(fall_model_path.read_bytes()).hexdigest(),
            "--fall-pose-normal-gate-enabled",
            "--frames-limit",
            "600",
        ],
    )

    with patch.object(main_module, "_build_source", return_value=source), patch.object(
        main_module, "run_pipeline_from_source"
    ) as mock_run:
        main_module.main()

    _, kwargs = mock_run.call_args
    assert kwargs["source"] is source
    assert kwargs["metrics_output_path"] == "outputs/run/metrics.json"
    assert kwargs["api_failed_events_output_path"] == "outputs/run/failures.jsonl"
    assert kwargs["fall_model_interval_frames"] == 3
    assert kwargs["fall_pose_normal_gate_enabled"] is True
    assert kwargs["frames_limit"] == 600
