"""Phase 4 Cause·Tracking 평가 지표를 reviewed artifact에서 산출한다.

Cause top-1은 다중 인원 세트의 timely 대표 Event를 사용한다. cause=null
specificity는 같은 actor·카메라의 단독 낙상 보조 세트를 사용한다. victim과
Cause actor는 독립적으로 채점하며 no-fall false alarm은 Cause 분모에서 뺀다.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Mapping, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

import phase4_recording_contract as contract  # noqa: E402
import phase4_tracker_comparison_contract as comparison_contract  # noqa: E402


TOP1_TARGET = 0.80
NULL_SPECIFICITY_TARGET = 0.90


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--annotations", required=True)
    parser.add_argument("--multiperson-events", required=True)
    parser.add_argument("--cause-null-events", required=True)
    parser.add_argument("--official-eval", required=True)
    parser.add_argument("--event-review", required=True)
    parser.add_argument("--switches", required=True)
    parser.add_argument("--selected-profile", required=True)
    parser.add_argument("--tracker-comparison-config", default=None)
    parser.add_argument(
        "--tracker-arm-id", choices=comparison_contract.ARM_IDS, default=None
    )
    parser.add_argument("--output", required=True)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def _representative_frame(
    event_frames: Sequence[int],
    annotation: Mapping[str, str],
    manifest: Mapping[str, str],
    protocol: Mapping,
) -> int | None:
    fall_start = int(annotation["fall_start_frame"])
    fps = float(manifest["fps"])
    start = fall_start - round(float(protocol["early_tolerance_sec"]) * fps)
    end = fall_start + round(float(protocol["timely_window_sec"]) * fps)
    candidates = sorted(frame for frame in event_frames if start <= frame <= end)
    return candidates[0] if candidates else None


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def validate_replay_provenance(
    replay: Mapping,
    *,
    selected_execution_profile_sha256: str,
    manifest_sha256: str,
    annotations_sha256: str,
    config_sha256: str,
) -> None:
    expected = {
        "selected_execution_profile_sha256": selected_execution_profile_sha256,
        "recordings_manifest_sha256": manifest_sha256,
        "fall_cause_annotations_sha256": annotations_sha256,
        "config_sha256": config_sha256,
    }
    errors = [
        f"{key}: replay={replay.get(key)!r}, expected={value!r}"
        for key, value in expected.items()
        if replay.get(key) != value
    ]
    if errors:
        raise ValueError("replay provenance 불일치:\n  - " + "\n  - ".join(errors))


def build_summary(
    *,
    manifest_rows: Sequence[Mapping[str, str]],
    annotation_rows: Sequence[Mapping[str, str]],
    multiperson_replay: Mapping,
    cause_null_replay: Mapping,
    official_eval: Mapping,
    event_review_rows: Sequence[Mapping[str, str]],
    switch_rows: Sequence[Mapping[str, str]],
    selected_profile: Mapping,
) -> dict:
    manifest_by_video = {row["video_id"]: row for row in manifest_rows}
    annotation_by_video = {row["video_id"]: row for row in annotation_rows}
    official_by_video = {row["video_id"]: row for row in official_eval["videos"]}
    multi_videos = multiperson_replay["videos"]
    multi_video_ids = {row["video_id"] for row in multi_videos}
    reviewed_video_ids = {row["video_id"] for row in event_review_rows}

    errors: list[str] = []
    if any(row["review_status"] != "reviewed" for row in event_review_rows):
        errors.append("event attribution review에 reviewed가 아닌 행이 있습니다.")
    missing_coverage = sorted(multi_video_ids - reviewed_video_ids)
    extra_coverage = sorted(reviewed_video_ids - multi_video_ids)
    if missing_coverage:
        errors.append(f"event review coverage 누락: {missing_coverage}")
    if extra_coverage:
        errors.append(f"event review에 replay 대상 밖 video_id가 있습니다: {extra_coverage}")
    for video_id in multi_video_ids:
        if video_id not in manifest_by_video or video_id not in annotation_by_video:
            errors.append(f"{video_id}: manifest 또는 annotation에 없습니다.")
        if video_id not in official_by_video:
            errors.append(f"{video_id}: 공식 평가 결과에 없습니다.")
    if errors:
        raise ValueError("Cause·Tracking summary 입력 검증 실패:\n  - " + "\n  - ".join(errors))

    protocol = selected_profile["evaluation_protocol"]
    review_by_video_frame = {
        (row["video_id"], int(row["event_frame"])): row
        for row in event_review_rows
        if row["event_frame"]
    }

    top1_denominator = 0
    top1_correct = 0
    top1_matched_events = 0
    top1_missed_falls = 0
    top1_late_falls = 0
    top1_unmatched_events = 0
    missed_cause = 0
    wrong_cause_actor = 0
    victim_mismatch = 0
    top1_by_actor: dict[str, dict[str, int]] = {}
    for video in multi_videos:
        video_id = video["video_id"]
        annotation = annotation_by_video[video_id]
        if annotation["cause_candidate_exists"] != "true":
            continue
        actor_id = annotation["victim_actor_id"] or "unknown"
        actor_stats = top1_by_actor.setdefault(
            actor_id,
            {
                "correct": 0,
                "denominator": 0,
                "matched_event_count": 0,
                "missed_fall": 0,
                "late_fall": 0,
                "unmatched_event": 0,
            },
        )
        top1_denominator += 1
        actor_stats["denominator"] += 1
        representative = _representative_frame(
            [event["frame_number"] for event in video["events"]],
            annotation,
            manifest_by_video[video_id],
            protocol,
        )
        if representative is None:
            if official_by_video[video_id].get("late_detection"):
                top1_late_falls += 1
                actor_stats["late_fall"] += 1
            elif not video["events"]:
                top1_missed_falls += 1
                actor_stats["missed_fall"] += 1
            else:
                top1_unmatched_events += 1
                actor_stats["unmatched_event"] += 1
            continue
        review = review_by_video_frame.get((video_id, representative))
        if review is None:
            raise ValueError(f"{video_id}@{representative}: reviewed Event 행이 없습니다.")
        top1_matched_events += 1
        actor_stats["matched_event_count"] += 1
        if review["victim_actor_id"] != annotation["victim_actor_id"]:
            victim_mismatch += 1
        predicted = review["predicted_cause_actor_id"]
        if predicted == annotation["cause_actor_id"]:
            top1_correct += 1
            actor_stats["correct"] += 1
        elif not predicted:
            missed_cause += 1
        else:
            wrong_cause_actor += 1

    null_denominator = 0
    null_correct = 0
    null_false_attribution = 0
    for video in cause_null_replay["videos"]:
        video_id = video["video_id"]
        annotation = annotation_by_video.get(video_id)
        manifest = manifest_by_video.get(video_id)
        if annotation is None or manifest is None or video_id not in official_by_video:
            raise ValueError(f"{video_id}: cause=null 평가 입력이 완전하지 않습니다.")
        if annotation["cause_candidate_exists"] != "false":
            raise ValueError(f"{video_id}: cause=null 평가에 후보 있음 영상이 포함됐습니다.")
        representative = _representative_frame(
            [event["frame_number"] for event in video["events"]],
            annotation,
            manifest,
            protocol,
        )
        if representative is None:
            continue
        event = next(
            item for item in video["events"] if item["frame_number"] == representative
        )
        null_denominator += 1
        if event["cause"] is None:
            null_correct += 1
        else:
            null_false_attribution += 1

    top1_accuracy = _ratio(top1_correct, top1_denominator)
    null_specificity = _ratio(null_correct, null_denominator)
    relation_counts = Counter(row["id_switch_relation"] for row in event_review_rows)
    error_counts = Counter(row["event_error_type"] for row in event_review_rows)
    caused_errors = relation_counts.get("caused", 0)
    comparison_reasons = []
    if caused_errors >= 2:
        comparison_reasons.append("repeated_id_switch_caused_event_errors")
    if top1_accuracy is not None and top1_accuracy < TOP1_TARGET:
        comparison_reasons.append("cause_top1_below_target")
    comparison_required = bool(comparison_reasons)

    return {
        "schema_version": "phase4_cause_tracking_summary_v1",
        "evaluation_protocol_version": protocol["version"],
        "tracker_comparison_policy_version": contract.TRACKER_COMPARISON_POLICY_VERSION,
        "scope": {
            "multiperson_videos": len(multi_video_ids),
            "cause_null_extension_videos": len(cause_null_replay["videos"]),
            "event_review_rows": len(event_review_rows),
            "reviewed_event_rows": sum(
                row["review_status"] == "reviewed" for row in event_review_rows
            ),
        },
        "cause_top1": {
            "correct": top1_correct,
            "denominator": top1_denominator,
            "accuracy": top1_accuracy,
            "target": TOP1_TARGET,
            "meets_target": (
                top1_accuracy >= TOP1_TARGET if top1_accuracy is not None else False
            ),
            "matched_event_count": top1_matched_events,
            "missed_fall": top1_missed_falls,
            "late_fall": top1_late_falls,
            "unmatched_event": top1_unmatched_events,
            "by_actor": {
                actor_id: {
                    **stats,
                    "accuracy": _ratio(stats["correct"], stats["denominator"]),
                }
                for actor_id, stats in sorted(top1_by_actor.items())
            },
            "missed_cause": missed_cause,
            "wrong_cause_actor": wrong_cause_actor,
            "victim_mismatch_scored_independently": victim_mismatch,
        },
        "cause_null_specificity": {
            "correct": null_correct,
            "denominator": null_denominator,
            "specificity": null_specificity,
            "target": NULL_SPECIFICITY_TARGET,
            "meets_target": (
                null_specificity >= NULL_SPECIFICITY_TARGET
                if null_specificity is not None
                else False
            ),
            "false_attribution": null_false_attribution,
        },
        "event_outcomes": dict(sorted(error_counts.items())),
        "tracking": {
            "reviewed_id_switches": sum(
                row["review_status"] == "reviewed" for row in switch_rows
            ),
            "id_switch_relations": dict(sorted(relation_counts.items())),
            "caused_event_errors": caused_errors,
            "tracker_comparison_required": comparison_required,
            "tracker_comparison_reasons": comparison_reasons,
            "comparison_order": [
                "bytetrack_baseline",
                "botsort_without_reid",
                "botsort_with_reid",
            ],
            "reid_experiment_status": (
                "required" if comparison_required else "not_required"
            ),
            "reid_production_status": (
                "pending_three_way_comparison"
                if comparison_required
                else "not_applicable"
            ),
        },
    }


def main() -> None:
    args = parse_args()
    output = Path(args.output)
    if output.exists() and not args.force:
        raise SystemExit(f"이미 존재합니다: {output} (--force로 덮어쓰기)")
    try:
        if bool(args.tracker_comparison_config) != bool(args.tracker_arm_id):
            raise ValueError(
                "--tracker-comparison-config와 --tracker-arm-id는 함께 지정해야 합니다."
            )
        manifest_rows = contract.load_recordings_manifest(args.manifest)
        annotation_rows = contract.load_fall_cause_annotations(
            args.annotations, manifest_rows, require_reviewed=True
        )
        event_review_rows = contract.load_event_attribution_review(
            args.event_review, manifest_rows
        )
        switch_rows = contract.load_track_id_switches(args.switches, manifest_rows)
        multiperson_replay = json.loads(
            Path(args.multiperson_events).read_text(encoding="utf-8")
        )
        cause_null_replay = json.loads(
            Path(args.cause_null_events).read_text(encoding="utf-8")
        )
        official_eval = json.loads(Path(args.official_eval).read_text(encoding="utf-8"))
        selected_profile = json.loads(
            Path(args.selected_profile).read_text(encoding="utf-8")
        )
        selected_execution_sha = contract.selected_execution_profile_sha256(
            selected_profile
        )
        manifest_sha = contract.sha256_file(args.manifest)
        annotations_sha = contract.sha256_file(args.annotations)
        config_sha = selected_profile["inference"]["fall_detector_config_sha256"]
        for replay in (multiperson_replay, cause_null_replay):
            validate_replay_provenance(
                replay,
                selected_execution_profile_sha256=selected_execution_sha,
                manifest_sha256=manifest_sha,
                annotations_sha256=annotations_sha,
                config_sha256=config_sha,
            )
        contract.validate_official_eval_provenance(
            official_eval,
            replay=multiperson_replay,
            selected_profile=selected_profile,
            selected_execution_profile_sha256=selected_execution_sha,
            recordings_manifest_sha256=manifest_sha,
            annotations_sha256=annotations_sha,
            config_sha256=config_sha,
        )
        comparison_arm = None
        if args.tracker_comparison_config:
            comparison = comparison_contract.load_config(
                args.tracker_comparison_config,
                require_model_artifacts=False,
            )
            comparison_contract.validate_cohort(
                comparison, manifest_rows, annotation_rows
            )
            comparison_arm = comparison_contract.arm_by_id(
                comparison, args.tracker_arm_id
            )
            expected_arm = comparison_contract.arm_provenance(comparison_arm)
            for name, replay in (
                ("multiperson", multiperson_replay),
                ("cause-null", cause_null_replay),
            ):
                if replay.get("tracker_comparison_arm") != expected_arm:
                    raise ValueError(f"{name} replay의 tracker arm provenance가 다릅니다.")
            comparison_contract.validate_cache_arm(
                {"tracker": official_eval.get("tracker_config") or {}},
                comparison_arm,
            )
        summary = build_summary(
            manifest_rows=manifest_rows,
            annotation_rows=annotation_rows,
            multiperson_replay=multiperson_replay,
            cause_null_replay=cause_null_replay,
            official_eval=official_eval,
            event_review_rows=event_review_rows,
            switch_rows=switch_rows,
            selected_profile=selected_profile,
        )
    except (OSError, ValueError, KeyError, StopIteration) as exc:
        raise SystemExit(str(exc)) from exc

    summary["provenance"] = {
        "selected_execution_profile_sha256": selected_execution_sha,
        "recordings_manifest_sha256": manifest_sha,
        "fall_cause_annotations_sha256": annotations_sha,
        "event_attribution_review_sha256": contract.sha256_file(args.event_review),
        "track_id_switches_sha256": contract.sha256_file(args.switches),
        "official_eval_sha256": contract.sha256_file(args.official_eval),
    }
    if comparison_arm is not None:
        summary["tracker_comparison_arm"] = comparison_contract.arm_provenance(
            comparison_arm
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\n결과 저장: {output}")


if __name__ == "__main__":
    main()
