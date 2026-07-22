"""Frame-loop performance metrics for the runtime pipeline."""

from __future__ import annotations

import json
import math
from pathlib import Path
from statistics import fmean
from typing import Dict, List, Optional


_METRICS_SCHEMA_VERSION = 1
_DEFAULT_WARMUP_FRAMES = 30


def _round_metric(value: Optional[float]) -> Optional[float]:
    return round(value, 6) if value is not None else None


def _nearest_rank_percentile(values: List[float], percentile: float) -> Optional[float]:
    """Return a nearest-rank percentile, or None when no samples exist."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(math.ceil(percentile * len(ordered)), 1)
    return ordered[rank - 1]


def _summarize(latencies_sec: List[float]) -> Dict[str, object]:
    total_elapsed_sec = sum(latencies_sec)
    processed_frames = len(latencies_sec)
    avg_fps = (
        processed_frames / total_elapsed_sec
        if processed_frames > 0 and total_elapsed_sec > 0
        else None
    )
    avg_latency_sec = fmean(latencies_sec) if latencies_sec else None

    return {
        "processed_frames": processed_frames,
        "total_elapsed_sec": _round_metric(total_elapsed_sec),
        "avg_fps": _round_metric(avg_fps),
        "avg_latency_sec": _round_metric(avg_latency_sec),
        "p95_latency_sec": _round_metric(
            _nearest_rank_percentile(latencies_sec, 0.95)
        ),
        "max_latency_sec": _round_metric(max(latencies_sec) if latencies_sec else None),
    }


class PipelineMetrics:
    """Collect latency samples without including model setup or shutdown flush."""

    def __init__(self, warmup_frames: int = _DEFAULT_WARMUP_FRAMES) -> None:
        if warmup_frames < 0:
            raise ValueError("warmup_frames must be non-negative")
        self.warmup_frames = warmup_frames
        self._latencies_sec: List[float] = []

    @property
    def processed_frames(self) -> int:
        return len(self._latencies_sec)

    def record(self, latency_sec: float) -> None:
        if latency_sec < 0:
            raise ValueError("latency_sec must be non-negative")
        self._latencies_sec.append(latency_sec)

    def to_dict(self) -> Dict[str, object]:
        warmup_frames_excluded = min(self.warmup_frames, self.processed_frames)
        all_frames = _summarize(self._latencies_sec)
        steady_state = _summarize(self._latencies_sec[warmup_frames_excluded:])
        return {
            "schema_version": _METRICS_SCHEMA_VERSION,
            "measurement_scope": "frame_loop_only",
            "warmup_frames": self.warmup_frames,
            "warmup_frames_excluded": warmup_frames_excluded,
            **all_frames,
            "steady_state": steady_state,
        }

    def write_json(self, output_path: str) -> None:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        with open(tmp_path, "w", encoding="utf-8") as file:
            json.dump(self.to_dict(), file, ensure_ascii=False, indent=2)
        tmp_path.replace(path)
