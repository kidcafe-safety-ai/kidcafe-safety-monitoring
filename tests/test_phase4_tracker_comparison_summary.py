from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import phase4_tracker_comparison_contract as contract  # noqa: E402
import summarize_phase4_tracker_comparison as summary  # noqa: E402


REPO_ROOT = Path(__file__).resolve().parent.parent


def _arm(arm_id, *, top1, switches, victim, fps=30.0):
    return {
        "arm_id": arm_id,
        "tracker_backend": "bytetrack" if arm_id == "bytetrack_baseline" else "botsort",
        "with_reid": arm_id == "botsort_with_reid",
        "cause_top1_correct": top1,
        "cause_top1_denominator": 8,
        "cause_top1_accuracy": top1 / 8,
        "cause_null_correct": 24,
        "cause_null_denominator": 24,
        "cause_null_specificity": 1.0,
        "recall": 0.9,
        "timely_recall": 0.9,
        "false_alarm_per_min": 0.0,
        "false_event_count": 0,
        "duplicate_events": 0,
        "victim_mismatch": victim,
        "reviewed_id_switches": switches,
        "avg_onset_latency_sec": 0.3,
        "fps_avg": fps,
        "provenance": {"evaluator_git_commit": "a" * 40},
    }


def _config():
    return {
        "policy_version": "phase4_tracker_comparison_policy_v1",
        "acceptance": {
            "cause_top1_min_correct": 7,
            "cause_top1_denominator": 8,
            "cause_null_specificity_min": 0.9,
            "recall_max_drop": 0.0,
            "timely_recall_max_drop": 0.0,
            "false_event_max_increase": 0,
            "duplicate_event_max_increase": 0,
            "victim_mismatch_must_decrease": True,
            "id_switch_must_decrease": True,
            "avg_onset_latency_max_increase_sec": 0.2,
            "fps_max_drop_ratio": 0.2,
        },
    }


def test_retains_baseline_when_no_candidate_passes_all_gates():
    result = summary.build_comparison(
        _config(),
        [
            _arm("bytetrack_baseline", top1=3, switches=15, victim=1),
            _arm("botsort_without_reid", top1=6, switches=10, victim=0),
            _arm("botsort_with_reid", top1=7, switches=15, victim=0),
        ],
    )

    assert result["decision"] == "baseline_retained"
    assert result["selected_arm"] == "bytetrack_baseline"
    assert result["reid_status"] == "not_adopted"


def test_adopts_reid_only_when_reid_arm_passes_all_gates():
    result = summary.build_comparison(
        _config(),
        [
            _arm("bytetrack_baseline", top1=3, switches=15, victim=1),
            _arm("botsort_without_reid", top1=6, switches=10, victim=0),
            _arm("botsort_with_reid", top1=7, switches=8, victim=0, fps=25.0),
        ],
    )

    assert result["decision"] == "candidate_adopted"
    assert result["selected_arm"] == "botsort_with_reid"
    assert result["reid_status"] == "adopted"


def test_keeps_nonproduction_fps_as_diagnostic_only():
    baseline = _arm("bytetrack_baseline", top1=3, switches=15, victim=1, fps=30.0)
    candidate = _arm("botsort_with_reid", top1=7, switches=8, victim=0, fps=23.9)

    result = summary.evaluate_candidate(candidate, baseline, _config()["acceptance"])

    assert result["diagnostic_checks"]["fps_within_limit"] is False
    assert result["passed"] is True


def test_rejects_tampered_immutable_artifact(tmp_path):
    config_path = REPO_ROOT / "configs/phase4_tracker_comparison.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    arm = config["arms"][0]
    source = (
        REPO_ROOT
        / "docs/phase4_tracker_comparison/results/arms/bytetrack_baseline"
    )
    arm_root = tmp_path / "bytetrack_baseline"
    shutil.copytree(source, arm_root)

    timing_path = arm_root / "cache/timing_report.json"
    timing = json.loads(timing_path.read_text(encoding="utf-8"))
    timing["fps_avg"] = 999.0
    timing_path.write_text(
        json.dumps(timing, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="timing_report SHA-256"):
        summary._load_arm_result(
            arm=arm,
            arm_root=arm_root,
            comparison_config_sha256=contract.sha256_file(config_path),
            ultralytics_version=config["ultralytics_version"],
        )
