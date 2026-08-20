"""검수 완료된 세 Tracker arm을 동결 기준으로 비교하고 채택 여부를 판정한다."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Mapping

sys.path.insert(0, str(Path(__file__).resolve().parent))

import phase4_tracker_comparison_contract as comparison_contract  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--comparison-config", default="configs/phase4_tracker_comparison.json"
    )
    parser.add_argument(
        "--results-root", default="outputs/phase4_tracker_comparison/arms"
    )
    parser.add_argument("--output", required=True)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def _false_event_count(official: Mapping) -> int:
    return sum(
        int(video["event_count"])
        for video in official["videos"]
        if video["label"] == "no_fall" and video.get("error") is None
    )


def _load_arm_result(
    *,
    arm: Mapping,
    arm_root: Path,
    comparison_config_sha256: str,
) -> dict:
    paths = {
        "run_manifest": arm_root / "arm_run_manifest.json",
        "official_eval": arm_root / "official_eval.json",
        "cause_summary": arm_root / "cause_tracking_summary.json",
        "timing_report": arm_root / "cache" / "timing_report.json",
    }
    missing = [str(path) for path in paths.values() if not path.is_file()]
    if missing:
        raise ValueError(f"{arm['arm_id']}: 결과 artifact가 없습니다: {missing}")

    run = json.loads(paths["run_manifest"].read_text(encoding="utf-8"))
    official = json.loads(paths["official_eval"].read_text(encoding="utf-8"))
    cause = json.loads(paths["cause_summary"].read_text(encoding="utf-8"))
    timing = json.loads(paths["timing_report"].read_text(encoding="utf-8"))
    expected_arm = comparison_contract.arm_provenance(arm)
    errors: list[str] = []
    if run.get("comparison_config_sha256") != comparison_config_sha256:
        errors.append("run manifest의 comparison config SHA-256이 다릅니다.")
    if run.get("arm") != expected_arm:
        errors.append("run manifest의 arm provenance가 다릅니다.")
    if run.get("evaluator_git_dirty") is not False:
        errors.append("run manifest가 dirty worktree 실행입니다.")
    if official.get("evaluator_git_dirty") is not False:
        errors.append("official evaluation이 dirty worktree 실행입니다.")
    if official.get("evaluator_git_commit") != run.get("evaluator_git_commit"):
        errors.append("run manifest와 official evaluation의 Git commit이 다릅니다.")
    if cause.get("tracker_comparison_arm") != expected_arm:
        errors.append("Cause summary의 arm provenance가 다릅니다.")
    if cause.get("provenance", {}).get("official_eval_sha256") != (
        comparison_contract.sha256_file(paths["official_eval"])
    ):
        errors.append("Cause summary가 현재 official eval을 참조하지 않습니다.")
    comparison_contract.validate_cache_arm(
        {"tracker": official.get("tracker_config") or {}}, arm
    )
    if not official.get("evaluation_valid"):
        errors.append("official evaluation이 유효하지 않습니다.")
    if timing.get("skipped_count") != 0:
        errors.append("FPS 비교 실행에서 건너뛴 영상이 있습니다.")
    if timing.get("videos_timed") != official.get("fall_videos", 0) + official.get(
        "no_fall_videos", 0
    ):
        errors.append("FPS 측정 영상 수와 공식 평가 영상 수가 다릅니다.")
    if errors:
        raise ValueError(f"{arm['arm_id']} 입력 검증 실패:\n  - " + "\n  - ".join(errors))

    top1 = cause["cause_top1"]
    null = cause["cause_null_specificity"]
    return {
        "arm_id": arm["arm_id"],
        "tracker_backend": arm["tracker_backend"],
        "with_reid": arm["with_reid"],
        "cause_top1_correct": top1["correct"],
        "cause_top1_denominator": top1["denominator"],
        "cause_top1_accuracy": top1["accuracy"],
        "cause_null_correct": null["correct"],
        "cause_null_denominator": null["denominator"],
        "cause_null_specificity": null["specificity"],
        "recall": official["recall"],
        "timely_recall": official["timely_recall"],
        "false_alarm_per_min": official["false_alarm_per_min"],
        "false_event_count": _false_event_count(official),
        "duplicate_events": official["duplicate_events"],
        "victim_mismatch": top1["victim_mismatch_scored_independently"],
        "reviewed_id_switches": cause["tracking"]["reviewed_id_switches"],
        "avg_onset_latency_sec": official["avg_onset_latency_sec"],
        "fps_avg": timing["fps_avg"],
        "provenance": {
            "evaluator_git_commit": run["evaluator_git_commit"],
            "arm_run_manifest_sha256": comparison_contract.sha256_file(
                paths["run_manifest"]
            ),
            "official_eval_sha256": comparison_contract.sha256_file(
                paths["official_eval"]
            ),
            "cause_summary_sha256": comparison_contract.sha256_file(
                paths["cause_summary"]
            ),
            "timing_report_sha256": comparison_contract.sha256_file(
                paths["timing_report"]
            ),
        },
    }


def evaluate_candidate(
    candidate: Mapping,
    baseline: Mapping,
    acceptance: Mapping,
) -> dict:
    checks = {
        "cause_top1": (
            candidate["cause_top1_denominator"]
            == acceptance["cause_top1_denominator"]
            and candidate["cause_top1_correct"]
            >= acceptance["cause_top1_min_correct"]
        ),
        "cause_null_specificity": (
            candidate["cause_null_specificity"] is not None
            and candidate["cause_null_specificity"]
            >= acceptance["cause_null_specificity_min"]
        ),
        "recall_no_regression": (
            candidate["recall"]
            >= baseline["recall"] - acceptance["recall_max_drop"]
        ),
        "timely_recall_no_regression": (
            candidate["timely_recall"]
            >= baseline["timely_recall"] - acceptance["timely_recall_max_drop"]
        ),
        "false_events_no_increase": (
            candidate["false_event_count"]
            <= baseline["false_event_count"]
            + acceptance["false_event_max_increase"]
        ),
        "duplicates_no_increase": (
            candidate["duplicate_events"]
            <= baseline["duplicate_events"]
            + acceptance["duplicate_event_max_increase"]
        ),
        "victim_mismatch_decreased": (
            candidate["victim_mismatch"] < baseline["victim_mismatch"]
            if acceptance["victim_mismatch_must_decrease"]
            else candidate["victim_mismatch"] <= baseline["victim_mismatch"]
        ),
        "id_switch_decreased": (
            candidate["reviewed_id_switches"] < baseline["reviewed_id_switches"]
            if acceptance["id_switch_must_decrease"]
            else candidate["reviewed_id_switches"]
            <= baseline["reviewed_id_switches"]
        ),
        "latency_within_limit": (
            candidate["avg_onset_latency_sec"]
            <= baseline["avg_onset_latency_sec"]
            + acceptance["avg_onset_latency_max_increase_sec"]
        ),
        "fps_within_limit": (
            candidate["fps_avg"]
            >= baseline["fps_avg"] * (1.0 - acceptance["fps_max_drop_ratio"])
        ),
    }
    return {
        "checks": checks,
        "passed": all(checks.values()),
        "deltas_from_baseline": {
            "cause_top1_correct": (
                candidate["cause_top1_correct"] - baseline["cause_top1_correct"]
            ),
            "recall": candidate["recall"] - baseline["recall"],
            "timely_recall": candidate["timely_recall"] - baseline["timely_recall"],
            "false_event_count": (
                candidate["false_event_count"] - baseline["false_event_count"]
            ),
            "duplicate_events": (
                candidate["duplicate_events"] - baseline["duplicate_events"]
            ),
            "victim_mismatch": (
                candidate["victim_mismatch"] - baseline["victim_mismatch"]
            ),
            "reviewed_id_switches": (
                candidate["reviewed_id_switches"]
                - baseline["reviewed_id_switches"]
            ),
            "avg_onset_latency_sec": (
                candidate["avg_onset_latency_sec"]
                - baseline["avg_onset_latency_sec"]
            ),
            "fps_drop_ratio": 1.0 - candidate["fps_avg"] / baseline["fps_avg"],
        },
    }


def build_comparison(config: Mapping, arm_results: list[dict]) -> dict:
    by_id = {result["arm_id"]: result for result in arm_results}
    baseline = by_id["bytetrack_baseline"]
    acceptance = config["acceptance"]
    commits = {
        result["provenance"]["evaluator_git_commit"] for result in arm_results
    }
    if len(commits) != 1:
        raise ValueError(f"세 arm의 evaluator Git commit이 다릅니다: {sorted(commits)}")
    evaluations = {
        arm_id: evaluate_candidate(by_id[arm_id], baseline, acceptance)
        for arm_id in comparison_contract.ARM_IDS[1:]
    }
    passing = [arm_id for arm_id, result in evaluations.items() if result["passed"]]
    if passing:
        preference = {
            "botsort_without_reid": 1,
            "botsort_with_reid": 0,
        }
        selected_arm = max(
            passing,
            key=lambda arm_id: (
                by_id[arm_id]["cause_top1_correct"],
                -by_id[arm_id]["victim_mismatch"],
                -by_id[arm_id]["reviewed_id_switches"],
                by_id[arm_id]["fps_avg"],
                preference[arm_id],
            ),
        )
        decision = "candidate_adopted"
        reid_status = (
            "adopted" if by_id[selected_arm]["with_reid"] else "not_needed"
        )
    else:
        selected_arm = "bytetrack_baseline"
        decision = "baseline_retained"
        reid_status = "not_adopted"
    return {
        "schema_version": "phase4_tracker_comparison_summary_v1",
        "policy_version": config["policy_version"],
        "decision": decision,
        "selected_arm": selected_arm,
        "reid_status": reid_status,
        "evaluator_git_commit": next(iter(commits)),
        "acceptance": acceptance,
        "arms": arm_results,
        "candidate_evaluations": evaluations,
    }


def main() -> None:
    args = parse_args()
    output = Path(args.output)
    if output.exists() and not args.force:
        raise SystemExit(f"이미 존재합니다: {output} (--force로 덮어쓰기)")
    try:
        config = comparison_contract.load_config(args.comparison_config)
        config_sha = comparison_contract.sha256_file(args.comparison_config)
        results_root = Path(args.results_root)
        arm_results = [
            _load_arm_result(
                arm=arm,
                arm_root=results_root / arm["arm_id"],
                comparison_config_sha256=config_sha,
            )
            for arm in config["arms"]
        ]
        summary = build_comparison(config, arm_results)
        summary["comparison_config_sha256"] = config_sha
    except (OSError, ValueError, KeyError, ZeroDivisionError) as exc:
        raise SystemExit(str(exc)) from exc
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\n결과 저장: {output}")


if __name__ == "__main__":
    main()
