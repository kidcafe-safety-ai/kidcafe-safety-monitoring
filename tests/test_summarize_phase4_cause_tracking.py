from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import summarize_phase4_cause_tracking as summarize  # noqa: E402


def _manifest(video_id: str) -> dict[str, str]:
    return {"video_id": video_id, "fps": "30"}


def _annotation(video_id: str, *, has_cause: bool) -> dict[str, str]:
    return {
        "video_id": video_id,
        "fall_start_frame": "100",
        "victim_actor_id": "A01",
        "cause_candidate_exists": "true" if has_cause else "false",
        "cause_actor_id": "A02" if has_cause else "",
    }


def _event(video_id: str, *, cause) -> dict:
    return {
        "video_id": video_id,
        "events": [{"frame_number": 110, "cause": cause}],
    }


def _review(video_id: str) -> dict[str, str]:
    return {
        "video_id": video_id,
        "event_frame": "110",
        "victim_actor_id": "A02",
        "predicted_cause_actor_id": "A01",
        "id_switch_relation": "none",
        "event_error_type": "victim_mismatch",
        "review_status": "reviewed",
    }


def _profile() -> dict:
    return {
        "evaluation_protocol": {
            "version": "phase4_fall_eval_v1",
            "early_tolerance_sec": 0.2,
            "timely_window_sec": 2.0,
        }
    }


def test_scores_victim_and_cause_independently_and_counts_null_extension():
    summary = summarize.build_summary(
        manifest_rows=[_manifest("contact"), _manifest("solo")],
        annotation_rows=[
            _annotation("contact", has_cause=True),
            _annotation("solo", has_cause=False),
        ],
        multiperson_replay={
            "videos": [_event("contact", cause={"track_id": 2})]
        },
        cause_null_replay={"videos": [_event("solo", cause=None)]},
        official_eval={"videos": [{"video_id": "contact"}, {"video_id": "solo"}]},
        event_review_rows=[_review("contact")],
        switch_rows=[],
        selected_profile=_profile(),
    )

    assert summary["cause_top1"] == {
        "correct": 0,
        "denominator": 1,
        "accuracy": 0.0,
        "target": 0.8,
        "meets_target": False,
        "missed_cause": 0,
        "wrong_cause_actor": 1,
        "victim_mismatch_scored_independently": 1,
    }
    assert summary["cause_null_specificity"]["correct"] == 1
    assert summary["cause_null_specificity"]["denominator"] == 1
    assert summary["cause_null_specificity"]["specificity"] == 1.0
    assert summary["tracking"]["tracker_comparison_required"] is True
    assert summary["tracking"]["tracker_comparison_reasons"] == [
        "cause_top1_below_target"
    ]
    assert summary["tracking"]["comparison_order"] == [
        "bytetrack_baseline",
        "botsort_without_reid",
        "botsort_with_reid",
    ]
    assert summary["tracking"]["reid_experiment_status"] == "required"


def test_rejects_missing_event_review_video_coverage():
    with pytest.raises(ValueError, match="coverage 누락"):
        summarize.build_summary(
            manifest_rows=[_manifest("contact")],
            annotation_rows=[_annotation("contact", has_cause=True)],
            multiperson_replay={
                "videos": [_event("contact", cause={"track_id": 2})]
            },
            cause_null_replay={"videos": []},
            official_eval={"videos": [{"video_id": "contact"}]},
            event_review_rows=[],
            switch_rows=[],
            selected_profile=_profile(),
        )


def test_zero_denominator_is_not_evaluable_and_does_not_pass():
    summary = summarize.build_summary(
        manifest_rows=[_manifest("no_fall")],
        annotation_rows=[_annotation("no_fall", has_cause=False)],
        multiperson_replay={"videos": [{"video_id": "no_fall", "events": []}]},
        cause_null_replay={"videos": []},
        official_eval={"videos": [{"video_id": "no_fall"}]},
        event_review_rows=[
            {
                "video_id": "no_fall",
                "event_frame": "",
                "victim_actor_id": "",
                "predicted_cause_actor_id": "",
                "id_switch_relation": "none",
                "event_error_type": "true_negative",
                "review_status": "reviewed",
            }
        ],
        switch_rows=[],
        selected_profile=_profile(),
    )

    assert summary["cause_top1"]["accuracy"] is None
    assert summary["cause_top1"]["meets_target"] is False
    assert summary["cause_null_specificity"]["specificity"] is None
    assert summary["cause_null_specificity"]["meets_target"] is False
    assert summary["tracking"]["tracker_comparison_required"] is False


def test_rejects_stale_replay_provenance():
    replay = {
        "selected_profile_sha256": "selected",
        "recordings_manifest_sha256": "stale",
        "fall_cause_annotations_sha256": "annotations",
        "config_sha256": "config",
    }

    with pytest.raises(ValueError, match="recordings_manifest_sha256"):
        summarize.validate_replay_provenance(
            replay,
            selected_profile_sha256="selected",
            manifest_sha256="manifest",
            annotations_sha256="annotations",
            config_sha256="config",
        )
