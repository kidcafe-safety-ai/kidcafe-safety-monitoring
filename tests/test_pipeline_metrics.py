"""Pipeline frame-loop metrics tests."""

from __future__ import annotations

import json

import pytest

from src.common.pipeline_metrics import PipelineMetrics


class TestPipelineMetrics:
    def test_empty_metrics_are_explicit(self):
        metrics = PipelineMetrics(warmup_frames=30).to_dict()

        assert metrics["processed_frames"] == 0
        assert metrics["total_elapsed_sec"] == 0
        assert metrics["avg_fps"] is None
        assert metrics["p95_latency_sec"] is None
        assert metrics["steady_state"]["processed_frames"] == 0

    def test_reports_all_and_steady_state_metrics(self):
        metrics = PipelineMetrics(warmup_frames=2)
        for latency_sec in [0.1, 0.2, 0.3, 0.4]:
            metrics.record(latency_sec)

        result = metrics.to_dict()

        assert result["processed_frames"] == 4
        assert result["warmup_frames_excluded"] == 2
        assert result["total_elapsed_sec"] == pytest.approx(1.0)
        assert result["avg_fps"] == pytest.approx(4.0)
        assert result["avg_latency_sec"] == pytest.approx(0.25)
        assert result["p95_latency_sec"] == pytest.approx(0.4)
        assert result["max_latency_sec"] == pytest.approx(0.4)

        steady_state = result["steady_state"]
        assert steady_state["processed_frames"] == 2
        assert steady_state["total_elapsed_sec"] == pytest.approx(0.7)
        assert steady_state["avg_fps"] == pytest.approx(2 / 0.7)
        assert steady_state["avg_latency_sec"] == pytest.approx(0.35)

    def test_nearest_rank_p95_uses_observed_sample(self):
        metrics = PipelineMetrics(warmup_frames=0)
        for latency_sec in range(1, 21):
            metrics.record(float(latency_sec))

        assert metrics.to_dict()["p95_latency_sec"] == 19.0

    def test_rejects_invalid_values(self):
        with pytest.raises(ValueError, match="warmup_frames"):
            PipelineMetrics(warmup_frames=-1)

        metrics = PipelineMetrics()
        with pytest.raises(ValueError, match="latency_sec"):
            metrics.record(-0.1)

    def test_write_json_creates_parent_and_replaces_temp_file(self, tmp_path):
        output_path = tmp_path / "nested" / "metrics.json"
        metrics = PipelineMetrics(warmup_frames=0)
        metrics.record(0.25)

        metrics.write_json(str(output_path))

        payload = json.loads(output_path.read_text(encoding="utf-8"))
        assert payload["schema_version"] == 1
        assert payload["measurement_scope"] == "frame_loop_only"
        assert payload["processed_frames"] == 1
        assert not output_path.with_suffix(".json.tmp").exists()
