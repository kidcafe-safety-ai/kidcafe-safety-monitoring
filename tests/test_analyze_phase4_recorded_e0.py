"""Phase 4 직접 촬영 E0 미탐 진단 테스트."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest

from src.common.types import Track
from src.safety.auxiliary_fall_model import FallDetection

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import analyze_phase4_recorded_e0 as analyzer  # noqa: E402
import fall_signal_cache as signal_cache  # noqa: E402


def _track(frame_number: int) -> Track:
    if frame_number < 3:
        bbox = [40.0, 0.0, 60.0, 60.0]
    elif frame_number == 3:
        bbox = [30.0, 20.0, 70.0, 60.0]
    else:
        bbox = [10.0, 50.0, 90.0, 70.0]
    return Track(
        track_id=1,
        bbox=bbox,
        foot_point=[(bbox[0] + bbox[2]) / 2, bbox[3]],
        confidence=0.9,
    )


def _write_fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    cache_dir = tmp_path / "cache"
    frames = [
        signal_cache.CachedFrame(
            frame_number=index,
            timestamp=f"00:00:00.{index * 100:03d}",
            tracks=[_track(index)],
            raw_detections=[
                FallDetection(
                    bbox=list(_track(index).bbox),
                    label="fall" if index >= 4 else "nofall",
                    confidence=0.9,
                )
            ],
        )
        for index in range(10)
    ]
    signal_cache.write_video_cache(
        cache_dir / "P4_S01_A01_fall_side_01_cam01.json",
        "P4_S01_A01_fall_side_01_cam01",
        10.0,
        {"tracker_type": "pose"},
        {"model_sha256": "a" * 64},
        frames,
    )
    annotations_path = tmp_path / "annotations.csv"
    with open(annotations_path, "w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=["video_id", "fall_start_frame"])
        writer.writeheader()
        writer.writerow(
            {
                "video_id": "P4_S01_A01_fall_side_01_cam01",
                "fall_start_frame": 3,
            }
        )
    config_path = Path(__file__).resolve().parent.parent / "configs/fall_detection.json"
    dataset = {
        "annotation_schema_version": "phase4_fall_cause_v1",
        "annotations_sha256": analyzer._sha256_file(annotations_path),
        "split": "diagnostic",
        "video_count": 1,
        "recordings_manifest_sha256": "b" * 64,
    }
    (cache_dir / "manifest.json").write_text(
        json.dumps({"dataset": dataset}), encoding="utf-8"
    )
    evaluation_path = tmp_path / "evaluation.json"
    evaluation_path.write_text(
        json.dumps(
            {
                "evaluation_valid": True,
                "split": "diagnostic",
                "dataset": dataset,
                "config_sha256": analyzer._sha256_file(config_path),
                "early_tolerance_sec": 0.2,
                "timely_window_sec": 0.5,
                "run_config": {"fall_model_iou_threshold": 0.3},
                "videos": [
                    {
                        "video_id": "P4_S01_A01_fall_side_01_cam01",
                        "label": "fall",
                        "event_count": 0,
                        "timely_detected": False,
                        "track_coverage": 1.0,
                        "id_switch_count": 0,
                        "error": None,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return evaluation_path, annotations_path, cache_dir, config_path


def test_analyze_reports_candidate_posture_and_model_evidence(tmp_path):
    evaluation, annotations, cache_dir, config = _write_fixture(tmp_path)

    payload = analyzer.analyze(evaluation, annotations, cache_dir, config)

    record = payload["videos"][0]
    assert record["scenario"] == "fall_side"
    assert record["dynamic_candidate_frame_count"] > 0
    assert record["horizontal_posture_frames"] > 0
    assert record["raw_model_fall_frames"] > 0
    assert record["matched_model_fall_frames"] > 0
    assert record["max_aspect_ratio"] == pytest.approx(4.0)
    assert payload["summary"]["model_fall_video_count"] == 1
    assert payload["sources"]["evaluation_sha256"]


def test_analyze_rejects_non_diagnostic_split(tmp_path):
    evaluation, annotations, cache_dir, config = _write_fixture(tmp_path)
    payload = json.loads(evaluation.read_text(encoding="utf-8"))
    payload["split"] = "test"
    evaluation.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(analyzer.RecordedE0AnalysisError, match="diagnostic split"):
        analyzer.analyze(evaluation, annotations, cache_dir, config)


def test_load_evaluation_rejects_video_error(tmp_path):
    evaluation, _, _, _ = _write_fixture(tmp_path)
    payload = json.loads(evaluation.read_text(encoding="utf-8"))
    payload["videos"][0]["error"] = "broken"
    evaluation.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(analyzer.RecordedE0AnalysisError, match="오류 영상"):
        analyzer.load_evaluation(evaluation)


def test_write_output_is_atomic(tmp_path):
    output = tmp_path / "result.json"

    analyzer.write_output(output, {"ok": True})

    assert json.loads(output.read_text(encoding="utf-8")) == {"ok": True}
    assert not output.with_suffix(".json.tmp").exists()
