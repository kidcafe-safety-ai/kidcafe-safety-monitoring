"""실제 RGB false Event 분석 도구 테스트."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import analyze_real_rgb_false_events as analyzer  # noqa: E402


def _cohort() -> tuple[dict, dict[str, dict]]:
    video = {
        "video_id": "gmd_adl_01",
        "label": "no_fall",
        "video_path": "videos/validation/adl/gmd_adl_01.mp4",
        "subject_id": 4,
        "split_role": "validation",
        "activity_name": "adl",
        "temporal_labels": [
            {"label": "walking", "start_sec": 0.0, "end_sec": 1.5},
            {"label": "sitting", "start_sec": 1.5, "end_sec": 5.0},
        ],
        "output_probe": {
            "fps": 20.0,
            "duration_sec": 5.0,
            "frame_count": 100,
        },
    }
    manifest = {
        "schema_version": "real_rgb_fall_cohort_v1",
        "source_dataset": "GMDCSA24",
        "video_count": 1,
        "videos": [video],
    }
    return manifest, {video["video_id"]: video}


def _evaluation() -> list[dict]:
    return [
        {
            "video_id": "gmd_adl_01",
            "label": "no_fall",
            "event_count": 2,
            "event_frames": [20, 60],
            "event_diagnostics": [
                {
                    "frame_number": 20,
                    "track_id": 7,
                    "confirm_path": "bbox",
                    "candidate_entry_reason": "model",
                },
                {
                    "frame_number": 60,
                    "track_id": 7,
                    "confirm_path": "bbox",
                    "candidate_entry_reason": "dynamic",
                },
            ],
            "duration_sec": 5.0,
            "error": None,
        }
    ]


def _cache(tmp_path: Path, fps: float = 20.0) -> Path:
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    (cache_dir / "gmd_adl_01.json").write_text(
        json.dumps(
            {
                "video_id": "gmd_adl_01",
                "fps": fps,
                "frame_count": 100,
                "frames": [],
            }
        ),
        encoding="utf-8",
    )
    (cache_dir / "manifest.json").write_text("{}", encoding="utf-8")
    return cache_dir


def test_routes_model_entry_and_rule_only_events(tmp_path):
    manifest, by_id = _cohort()

    records, summary = analyzer.analyze(
        _evaluation(), manifest, by_id, _cache(tmp_path), 1.0
    )

    assert [record["diagnostic_route"] for record in records] == [
        "aux_model_involved",
        "rule_only",
    ]
    assert records[0]["active_labels"] == ["walking"]
    assert records[1]["active_labels"] == ["sitting"]
    assert records[0]["review_start_sec"] == 0.0
    assert summary["false_event_count"] == 2
    assert summary["diagnostic_route"] == {
        "aux_model_involved": 1,
        "rule_only": 1,
    }


def test_ignores_fall_events_for_false_event_routing(tmp_path):
    manifest, by_id = _cohort()
    fall_video = dict(by_id["gmd_adl_01"])
    fall_video.update({"video_id": "gmd_fall_01", "label": "fall"})
    manifest["video_count"] = 2
    manifest["videos"].append(fall_video)
    by_id["gmd_fall_01"] = fall_video
    evaluation = _evaluation()
    evaluation.append(
        {
            "video_id": "gmd_fall_01",
            "label": "fall",
            "event_count": 1,
            "event_frames": [20],
            "event_diagnostics": [
                {
                    "frame_number": 20,
                    "track_id": 1,
                    "confirm_path": "model",
                    "candidate_entry_reason": "dynamic",
                }
            ],
            "duration_sec": 5.0,
            "error": None,
        }
    )

    records, _ = analyzer.analyze(
        evaluation, manifest, by_id, _cache(tmp_path), 1.0
    )

    assert {record["video_id"] for record in records} == {"gmd_adl_01"}


def test_allows_small_container_fps_difference_when_frame_duration_matches(tmp_path):
    manifest, by_id = _cohort()
    by_id["gmd_adl_01"]["output_probe"]["fps"] = 19.6

    records, _ = analyzer.analyze(
        _evaluation(), manifest, by_id, _cache(tmp_path, fps=20.0), 1.0
    )

    assert len(records) == 2


def test_rejects_cohort_cache_duration_mismatch(tmp_path):
    manifest, by_id = _cohort()

    with pytest.raises(analyzer.AnalysisError, match="duration"):
        analyzer.analyze(
            _evaluation(), manifest, by_id, _cache(tmp_path, fps=19.0), 1.0
        )


def test_rejects_cohort_cache_frame_count_mismatch(tmp_path):
    manifest, by_id = _cohort()
    cache = _cache(tmp_path)
    cache_path = cache / "gmd_adl_01.json"
    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    payload["frame_count"] = 99
    cache_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(analyzer.AnalysisError, match="frame_count"):
        analyzer.analyze(_evaluation(), manifest, by_id, cache, 1.0)


def test_rejects_unknown_diagnostic_route(tmp_path):
    manifest, by_id = _cohort()
    evaluation = _evaluation()
    evaluation[0]["event_diagnostics"][0]["confirm_path"] = "unknown"

    with pytest.raises(analyzer.AnalysisError, match="confirm_path"):
        analyzer.analyze(evaluation, manifest, by_id, _cache(tmp_path), 1.0)


def test_load_evaluation_requires_valid_result(tmp_path):
    path = tmp_path / "evaluation.json"
    path.write_text(json.dumps({"evaluation_valid": False, "videos": []}))

    with pytest.raises(analyzer.AnalysisError, match="evaluation_valid"):
        analyzer.load_evaluation(path)


def test_write_outputs_records_source_hashes(tmp_path):
    output = tmp_path / "analysis"
    sources = {}
    for name in ("evaluation", "cohort_manifest", "cache_manifest"):
        path = tmp_path / f"{name}.json"
        path.write_text("{}", encoding="utf-8")
        sources[name] = path

    payload = analyzer.write_outputs(
        output,
        [],
        {"false_event_count": 0},
        sources,
        2.5,
        False,
    )

    assert payload["schema_version"] == "real_rgb_false_event_analysis_v1"
    assert (output / "false_events.csv").read_text().startswith("review_id,")
    assert set(payload["sources"]) == set(sources)
