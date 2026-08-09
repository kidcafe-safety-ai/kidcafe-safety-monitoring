"""Cached Fall Event motion coherence 분석 테스트."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from src.common.types import Track

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import analyze_fall_motion_coherence as analyzer  # noqa: E402
import fall_signal_cache as cache  # noqa: E402


def _track(frame_number: int, center_y: float, height: float = 10.0) -> Track:
    return Track(
        track_id=1,
        bbox=[0.0, center_y - height / 2, 10.0, center_y + height / 2],
        foot_point=[5.0, center_y + height / 2],
        confidence=0.9,
    )


def _cache(tmp_path: Path, centers: list[float]) -> Path:
    cache_dir = tmp_path / "cache"
    frames = [
        cache.CachedFrame(
            frame_number=index,
            timestamp=f"00:00:00.{index * 100:03d}",
            tracks=[_track(index, center)] if center is not None else [],
            raw_detections=[],
        )
        for index, center in enumerate(centers)
    ]
    cache.write_video_cache(
        cache_dir / "video_1.json",
        "video_1",
        10.0,
        {"tracker_type": "pose"},
        {"model_sha256": "a" * 64},
        frames,
    )
    (cache_dir / "manifest.json").write_text("{}", encoding="utf-8")
    return cache_dir


def _evaluation(label: str = "no_fall", confidence: float = 0.5) -> list[dict]:
    return [
        {
            "video_id": "video_1",
            "label": label,
            "event_count": 1,
            "event_frames": [5],
            "event_diagnostics": [
                {
                    "frame_number": 5,
                    "track_id": 1,
                    "confirm_path": "bbox",
                    "candidate_entry_reason": "dynamic",
                    "event_confidence": confidence,
                }
            ],
            "error": None,
        }
    ]


def test_analyze_records_monotonic_downward_motion(tmp_path):
    cache_dir = _cache(tmp_path, [10, 11, 12, 13, 14, 15])

    records, summary = analyzer.analyze(_evaluation(), cache_dir, window_sec=0.5)

    assert len(records) == 1
    record = records[0]
    assert record["visible_frame_ratio"] == 1.0
    assert record["motion_pair_count"] == 5
    assert record["center_downward_step_ratio"] == 1.0
    assert record["foot_downward_step_ratio"] == 1.0
    assert record["center_direction_reversal_count"] == 0
    assert record["net_center_descent_norm"] == pytest.approx(0.5)
    assert summary["by_label"]["no_fall"]["event_count"] == 1


def test_analyze_counts_direction_reversal(tmp_path):
    cache_dir = _cache(tmp_path, [10, 12, 11, 13, 12, 14])

    records, _ = analyzer.analyze(_evaluation(), cache_dir, window_sec=0.5)

    assert records[0]["center_direction_reversal_count"] == 4
    assert records[0]["center_downward_step_ratio"] == pytest.approx(0.6)


def test_analyze_rejects_event_without_two_same_track_samples(tmp_path):
    cache_dir = _cache(tmp_path, [None, None, None, None, None, 15])

    with pytest.raises(analyzer.MotionCoherenceError, match="2개 미만"):
        analyzer.analyze(_evaluation(), cache_dir, window_sec=0.5)


def test_load_evaluation_rejects_invalid_diagnostic_mapping(tmp_path):
    path = tmp_path / "evaluation.json"
    payload = {"evaluation_valid": True, "videos": _evaluation()}
    payload["videos"][0]["event_diagnostics"][0]["frame_number"] = 4
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(analyzer.MotionCoherenceError, match="대응"):
        analyzer.load_evaluation(path)


def test_write_outputs_keeps_source_hashes(tmp_path):
    evaluation_path = tmp_path / "evaluation.json"
    cache_manifest = tmp_path / "cache_manifest.json"
    evaluation_path.write_text("{}", encoding="utf-8")
    cache_manifest.write_text("{}", encoding="utf-8")
    record = {field: 0.0 for field in analyzer.CSV_FIELDS}
    record.update(
        {
            "video_id": "video_1",
            "label": "no_fall",
            "confirm_path": "bbox",
            "candidate_entry_reason": "dynamic",
        }
    )

    payload = analyzer.write_outputs(
        tmp_path / "output",
        [record],
        {"event_count": 1},
        evaluation_path,
        cache_manifest,
        0.8,
        False,
    )

    assert payload["schema_version"] == analyzer.SCHEMA_VERSION
    assert (tmp_path / "output" / analyzer.OUTPUT_CSV).is_file()
    assert payload["sources"]["evaluation_sha256"] == analyzer.sha256_file(evaluation_path)
