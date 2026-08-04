"""OmniFall false Event temporal label 조인 테스트."""

from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import analyze_omnifall_false_events as analyzer  # noqa: E402


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _inputs(tmp_path: Path, active_label: int = 3):
    evaluation_path = _write_json(
        tmp_path / "evaluation.json",
        {
            "evaluation_valid": True,
            "videos": [
                {
                    "video_id": "ofsyn_sit_down_a",
                    "label": "no_fall",
                    "event_count": 2,
                    "event_frames": [20, 40],
                    "event_diagnostics": [
                        {
                            "frame_number": 20,
                            "track_id": 1,
                            "confirm_path": "model",
                            "candidate_entry_reason": "model",
                        },
                        {
                            "frame_number": 40,
                            "track_id": 1,
                            "confirm_path": "bbox",
                            "candidate_entry_reason": "dynamic",
                        },
                    ],
                    "duration_sec": 5.0,
                    "error": None,
                }
            ],
        },
    )
    cohort_path = _write_json(
        tmp_path / "cohort_manifest.json",
        {
            "schema_version": analyzer.COHORT_SCHEMA_VERSION,
            "video_count": 1,
            "videos": [
                {
                    "video_id": "ofsyn_sit_down_a",
                    "source_path": "sit_down/a",
                }
            ],
        },
    )
    labels_path = tmp_path / "labels.csv"
    with labels_path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=["path", "label", "start", "end"])
        writer.writeheader()
        writer.writerow(
            {"path": "sit_down/a", "label": active_label, "start": 0, "end": 5}
        )
    cache_dir = tmp_path / "cache"
    _write_json(
        cache_dir / "ofsyn_sit_down_a.json",
        {"video_id": "ofsyn_sit_down_a", "fps": 20.0},
    )
    _write_json(cache_dir / "manifest.json", {"cache": "manifest"})
    return evaluation_path, cohort_path, labels_path, cache_dir


def test_joins_event_frames_to_labels_and_routes_confirm_paths(tmp_path):
    evaluation, cohort, labels, cache_dir = _inputs(tmp_path)

    videos = analyzer._load_evaluation(evaluation)
    records, summary = analyzer.analyze(
        videos,
        analyzer._load_cohort_paths(cohort),
        analyzer._load_labels(labels),
        cache_dir,
        1.0,
    )

    assert [record["event_sec"] for record in records] == [1.0, 2.0]
    assert all(record["active_labels"] == ["sit_down"] for record in records)
    assert [record["diagnostic_route"] for record in records] == [
        "aux_model",
        "rule_or_temporal",
    ]
    assert all(record["review_status"] == "pending" for record in records)
    assert all(record["selected_for_training"] is False for record in records)
    assert summary["by_confirm_path"] == {"bbox": 1, "model": 1}
    assert summary["diagnostic_route"] == {"aux_model": 1, "rule_or_temporal": 1}


def test_positive_label_overlap_is_rejected(tmp_path):
    evaluation, cohort, labels, cache_dir = _inputs(tmp_path, active_label=1)

    with pytest.raises(analyzer.AnalysisError, match="positive label"):
        analyzer.analyze(
            analyzer._load_evaluation(evaluation),
            analyzer._load_cohort_paths(cohort),
            analyzer._load_labels(labels),
            cache_dir,
            1.0,
        )


def test_invalid_evaluation_is_rejected(tmp_path):
    evaluation, _, _, _ = _inputs(tmp_path)
    payload = json.loads(evaluation.read_text(encoding="utf-8"))
    payload["evaluation_valid"] = False
    evaluation.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(analyzer.AnalysisError, match="evaluation_valid"):
        analyzer._load_evaluation(evaluation)


def test_event_diagnostics_must_match_event_frames(tmp_path):
    evaluation, _, _, _ = _inputs(tmp_path)
    payload = json.loads(evaluation.read_text(encoding="utf-8"))
    payload["videos"][0]["event_diagnostics"][1]["frame_number"] = 41
    evaluation.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(analyzer.AnalysisError, match="대응하지 않습니다"):
        analyzer._load_evaluation(evaluation)


def test_outputs_include_source_and_csv_checksums(tmp_path):
    evaluation, cohort, labels, cache_dir = _inputs(tmp_path)
    records, summary = analyzer.analyze(
        analyzer._load_evaluation(evaluation),
        analyzer._load_cohort_paths(cohort),
        analyzer._load_labels(labels),
        cache_dir,
        1.0,
    )
    output = tmp_path / "output"

    payload = analyzer.write_outputs(
        output,
        records,
        summary,
        {
            "evaluation": evaluation,
            "cohort_manifest": cohort,
            "labels": labels,
            "cache_manifest": cache_dir / "manifest.json",
        },
        1.0,
        False,
    )

    csv_path = output / analyzer.OUTPUT_CSV
    assert payload["schema_version"] == analyzer.ANALYSIS_SCHEMA_VERSION
    assert payload["false_events_csv_sha256"] == hashlib.sha256(
        csv_path.read_bytes()
    ).hexdigest()
    assert all(source["sha256"] for source in payload["sources"].values())


def test_existing_output_requires_force(tmp_path):
    output = tmp_path / "output"
    output.mkdir()
    (output / analyzer.OUTPUT_CSV).write_text("existing", encoding="utf-8")

    with pytest.raises(analyzer.AnalysisError, match="force"):
        analyzer.write_outputs(output, [], {}, {}, 1.0, False)


def test_module_entrypoint_help_works():
    repository_root = Path(__file__).resolve().parent.parent

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.analyze_omnifall_false_events",
            "--help",
        ],
        cwd=repository_root,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "--evaluation" in result.stdout
