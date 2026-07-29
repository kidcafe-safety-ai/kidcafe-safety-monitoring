import csv
import json
import math
import re
from datetime import datetime
from itertools import combinations
from pathlib import Path


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "phase4_contract"
VERSION_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
VIDEO_ID_PATTERN = re.compile(
    r"^P4_S\d{2}_A\d{2}_[a-z0-9_]+_\d{2}_cam\d{2}$"
)
SCENARIO_PATTERN = re.compile(r"^[a-z0-9]+(?:_[a-z0-9]+)*$")


def _load_json(name):
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def _load_csv(name):
    with (FIXTURE_DIR / name).open(encoding="utf-8", newline="") as file:
        reader = csv.DictReader(file)
        return reader.fieldnames, list(reader)


def _assert_success_envelope(payload):
    assert payload["status"] == "success"
    assert payload["message"] is None
    assert payload["data"] is not None


def _assert_open_polygon(points):
    assert len(points) >= 3
    assert points[0] != points[-1]
    assert len({tuple(point) for point in points}) == len(points)
    assert all(0.0 <= coordinate <= 1.0 for point in points for coordinate in point)


def _has_non_collinear_points(points):
    for first, second, third in combinations(points, 3):
        cross_product = (
            (second[0] - first[0]) * (third[1] - first[1])
            - (second[1] - first[1]) * (third[0] - first[0])
        )
        if not math.isclose(cross_product, 0.0):
            return True
    return False


def test_contract_manifest_freezes_machine_readable_versions_and_rule_ids():
    payload = _load_json("contract_manifest.json")

    assert payload["contract_version"] == "phase4_contract_v1"
    assert payload["evaluation_protocol_version"] == "phase4_fall_eval_v1"
    assert payload["homography_acceptance_version"] == "homography_acceptance_v1"
    assert payload["annotation_schema_versions"] == {
        "caucafall": "caucafall_annotation_v2",
        "recordings_manifest": "phase4_recordings_manifest_v1",
        "fall_cause": "phase4_fall_cause_v1",
        "zone_intervals": "phase4_zone_intervals_v1",
        "calibration_points": "phase4_calibration_points_v1",
        "track_actor_review": "phase4_track_actor_review_v1",
    }
    assert payload["evaluation_rule_ids"] == {
        "event_matching_rule": "first_fall_suspect_in_closed_timely_window_v1",
        "duplicate_rule": "second_fall_suspect_from_window_start_to_video_end_v1",
        "far_denominator_rule": "processed_no_fall_frames_over_fps_v1",
    }


def test_event_query_fixture_uses_aware_half_open_range_and_valid_filters():
    payload = _load_json("events_query.json")

    created_from = datetime.fromisoformat(payload["created_from"])
    created_to = datetime.fromisoformat(payload["created_to"])
    assert created_from.tzinfo is not None
    assert created_to.tzinfo is not None
    assert created_from < created_to
    assert 1 <= payload["limit"] <= 500
    assert payload["offset"] >= 0
    assert payload["event_type"] == "FALL_SUSPECT"
    assert payload["zone_id"]


def test_event_page_fixtures_keep_pagination_envelope_and_stable_order():
    payload = _load_json("events_page_success.json")
    _assert_success_envelope(payload)

    data = payload["data"]
    assert data["count"] == len(data["items"])
    assert data["total"] >= data["count"]
    sort_keys = [
        (item["created_at"], item["id"])
        for item in data["items"]
    ]
    assert sort_keys == sorted(sort_keys, reverse=True)

    empty = _load_json("events_page_empty.json")
    _assert_success_envelope(empty)
    assert empty["data"]["items"] == []
    assert empty["data"]["total"] == empty["data"]["count"] == 0


def test_validation_error_fixture_uses_fastapi_detail_shape():
    payload = _load_json("validation_error_422.json")

    assert "status" not in payload
    assert isinstance(payload["detail"], list)
    assert payload["detail"][0]["loc"] == ["query", "created_from"]


def test_zone_get_and_put_fixtures_define_versioned_full_replacement():
    get_payload = _load_json("zones_get_success.json")
    empty_payload = _load_json("zones_get_empty.json")
    put_request = _load_json("zones_put_request.json")
    put_payload = _load_json("zones_put_success.json")

    for payload in (get_payload, empty_payload, put_payload):
        _assert_success_envelope(payload)
        assert VERSION_PATTERN.fullmatch(payload["data"]["version"])
        assert payload["data"]["updated_at"].endswith("Z")

    assert put_request["expected_version"] == get_payload["data"]["version"]
    assert put_request["zones"] == put_payload["data"]["zones"]
    assert put_payload["data"]["version"] != put_request["expected_version"]
    assert empty_payload["data"]["zones"] == []

    for zone in put_request["zones"]:
        assert zone["type"] == "polygon"
        assert zone["zone_type"] in {"play", "exit", "restricted", "danger"}
        _assert_open_polygon(zone["points"])


def test_zone_error_fixtures_distinguish_application_and_validation_errors():
    unavailable = _load_json("zones_get_unavailable.json")
    invalid_file = _load_json("zones_get_invalid.json")
    conflict = _load_json("zones_version_conflict.json")
    invalid_polygon = _load_json("zones_invalid_polygon_422.json")

    for payload in (unavailable, invalid_file, conflict):
        assert payload["status"] == "error"
        assert payload["data"] is None
        assert payload["message"]

    assert invalid_file == unavailable
    assert "status" not in invalid_polygon
    assert invalid_polygon["detail"][0]["loc"][-1] == "points"


def test_calibration_runtime_fixture_contains_fit_points_only():
    payload = _load_json("calibration_runtime.json")

    assert payload["schema_version"] == 1
    assert payload["enabled"] is False
    assert payload["coordinate_unit"] == "meter"
    assert len(payload["image_points_px"]) == len(payload["floor_points"]) >= 4

    width = payload["frame_size"]["width"]
    height = payload["frame_size"]["height"]
    assert all(
        0.0 <= x < width and 0.0 <= y < height
        for x, y in payload["image_points_px"]
    )
    assert len({tuple(point) for point in payload["image_points_px"]}) >= 4
    assert len({tuple(point) for point in payload["floor_points"]}) >= 4
    assert _has_non_collinear_points(payload["image_points_px"])
    assert _has_non_collinear_points(payload["floor_points"])


def test_floor_zone_fixture_is_separate_meter_coordinate_contract():
    payload = _load_json("floor_zone_config.json")

    assert payload["schema_version"] == 1
    assert payload["camera_id"] == "cam01"
    assert payload["coordinate_space"] == "floor_meters"
    assert payload["zones"]
    for zone in payload["zones"]:
        assert zone["type"] == "polygon"
        assert zone["zone_type"] in {"play", "exit", "restricted", "danger"}
        assert len(zone["points"]) >= 3
        assert zone["points"][0] != zone["points"][-1]
        assert len({tuple(point) for point in zone["points"]}) == len(zone["points"])
        assert all(math.isfinite(value) for point in zone["points"] for value in point)


def test_homography_acceptance_fixture_is_pending_before_holdout():
    payload = _load_json("homography_acceptance.json")

    assert payload["protocol_version"] == "homography_acceptance_v1"
    assert payload["review_status"] == "pending"
    assert payload["frozen_at"] is None
    assert payload["max_mean_error_m"] is None
    assert payload["max_p95_error_m"] is None
    assert payload["min_zone_error_reduction_ratio"] == 0.30
    assert payload["min_event_error_reduction_ratio"] == 0.30
    assert payload["max_added_latency_ms_per_frame"] == 1.0
    assert payload["max_fps_drop_ratio"] == 0.05


def test_recording_manifest_fixture_uses_deidentified_contract():
    fields, rows = _load_csv("recordings_manifest.csv")

    assert fields == [
        "video_id",
        "session_id",
        "actor_ids",
        "primary_actor_id",
        "camera_id",
        "scenario_type",
        "label",
        "video_path",
        "fps",
        "frame_count",
        "width",
        "height",
        "lighting",
        "split_role",
        "review_status",
        "consent_status",
        "checksum_sha256",
    ]
    assert rows
    video_ids = {row["video_id"] for row in rows}
    assert len(video_ids) == len(rows)
    for row in rows:
        assert VIDEO_ID_PATTERN.fullmatch(row["video_id"])
        assert re.fullmatch(r"S\d{2}", row["session_id"])
        assert re.fullmatch(r"cam\d{2}", row["camera_id"])
        assert SCENARIO_PATTERN.fullmatch(row["scenario_type"])
        actor_ids = set(row["actor_ids"].split("|"))
        assert actor_ids
        assert all(re.fullmatch(r"A\d{2}", actor_id) for actor_id in actor_ids)
        assert row["primary_actor_id"] in actor_ids
        assert Path(row["video_path"]).name == f"{row['video_id']}.mp4"
        assert not Path(row["video_path"]).is_absolute()
        assert "\\" not in row["video_path"]
        assert float(row["fps"]) > 0
        assert int(row["frame_count"]) > 0
        assert int(row["width"]) > 0
        assert int(row["height"]) > 0
        assert row["label"] in {"fall", "no_fall"}
        assert row["split_role"] in {
            "train",
            "internal_validation",
            "diagnostic",
            "test",
            "external_evaluation",
        }
        assert row["review_status"] in {"pending", "needs_review", "reviewed"}
        assert row["consent_status"] in {"confirmed", "excluded"}
        assert re.fullmatch(r"[0-9a-f]{64}", row["checksum_sha256"])


def test_fall_cause_fixture_enforces_frame_order_and_two_reviewers():
    fields, rows = _load_csv("fall_cause_annotations.csv")
    _, manifest_rows = _load_csv("recordings_manifest.csv")
    manifest_by_video = {
        row["video_id"]: {
            "actors": set(row["actor_ids"].split("|")),
            "frame_count": int(row["frame_count"]),
            "label": row["label"],
        }
        for row in manifest_rows
    }

    assert {"reviewer_id", "second_reviewer_id"}.issubset(fields)
    assert len({row["video_id"] for row in rows}) == len(rows)
    for row in rows:
        assert row["video_id"] in manifest_by_video
        manifest = manifest_by_video[row["video_id"]]
        assert row["label"] == manifest["label"]
        assert row["review_status"] in {"pending", "needs_review", "reviewed"}
        assert row["contact_occurred"] in {"true", "false"}
        assert row["cause_candidate_exists"] in {"true", "false"}
        frames = []
        if row["label"] == "fall":
            frames = [
                int(row["fall_start_frame"]),
                int(row["impact_frame"]),
                int(row["lying_start_frame"]),
            ]
            if row["recovery_frame"]:
                frames.append(int(row["recovery_frame"]))
            assert frames == sorted(frames)
            assert row["victim_actor_id"]
        else:
            assert not row["fall_start_frame"]
            assert not row["impact_frame"]
            assert not row["lying_start_frame"]
            assert not row["recovery_frame"]

        assert all(0 <= frame < manifest["frame_count"] for frame in frames)
        if row["victim_actor_id"]:
            assert row["victim_actor_id"] in manifest["actors"]

        if row["review_status"] == "reviewed":
            assert row["reviewer_id"]
            assert row["second_reviewer_id"]
            assert row["reviewer_id"] != row["second_reviewer_id"]

        if row["contact_occurred"] == "true":
            assert row["contact_frame"]
            assert 0 <= int(row["contact_frame"]) < manifest["frame_count"]
        else:
            assert not row["contact_frame"]

        if row["cause_candidate_exists"] == "true":
            assert row["cause_actor_id"]
            assert row["cause_actor_id"] != row["victim_actor_id"]
            assert row["cause_actor_id"] in manifest["actors"]
        else:
            assert not row["cause_actor_id"]


def test_zone_and_calibration_annotation_fixtures_keep_holdout_separate():
    zone_fields, zone_rows = _load_csv("zone_intervals.csv")
    point_fields, point_rows = _load_csv("calibration_points.csv")
    _, manifest_rows = _load_csv("recordings_manifest.csv")
    frame_counts = {
        row["video_id"]: int(row["frame_count"])
        for row in manifest_rows
    }

    assert zone_fields[:6] == [
        "video_id",
        "zone_id",
        "interval_index",
        "enter_frame",
        "exit_frame",
        "dwell_start_frame",
    ]
    interval_keys = set()
    for row in zone_rows:
        assert row["video_id"] in frame_counts
        enter_frame = int(row["enter_frame"])
        exit_frame = int(row["exit_frame"])
        assert 0 <= enter_frame < exit_frame < frame_counts[row["video_id"]]
        assert int(row["interval_index"]) >= 1
        key = (row["video_id"], row["zone_id"], row["interval_index"])
        assert key not in interval_keys
        interval_keys.add(key)
        if row["dwell_start_frame"]:
            dwell_start_frame = int(row["dwell_start_frame"])
            assert enter_frame <= dwell_start_frame < exit_frame
        assert row["review_status"] in {"pending", "needs_review", "reviewed"}

    assert "point_role" in point_fields
    assert all(row["point_role"] in {"fit", "holdout"} for row in point_rows)

    fit_points = [row for row in point_rows if row["point_role"] == "fit"]
    holdout_points = [row for row in point_rows if row["point_role"] == "holdout"]
    assert len(fit_points) >= 4
    assert len(holdout_points) >= 20
    assert len({row["point_id"] for row in holdout_points}) >= 10
    assert {row["point_id"] for row in fit_points}.isdisjoint(
        {row["point_id"] for row in holdout_points}
    )
    observations = {
        (row["point_id"], row["observation_index"])
        for row in point_rows
    }
    assert len(observations) == len(point_rows)
    assert all(int(row["observation_index"]) >= 1 for row in point_rows)
    assert all(
        row["review_status"] in {"pending", "needs_review", "reviewed"}
        for row in point_rows
    )
    assert all(
        math.isfinite(float(row[field]))
        for row in point_rows
        for field in ("image_x_px", "image_y_px", "floor_x_m", "floor_y_m")
    )


def test_track_actor_and_switch_fixtures_support_multiple_switch_references():
    segment_fields, segments = _load_csv("track_actor_segments.csv")
    switch_fields, switches = _load_csv("track_id_switches.csv")
    review_fields, reviews = _load_csv("event_attribution_review.csv")

    assert segment_fields[:4] == ["run_id", "video_id", "start_frame", "end_frame"]
    assert "switch_id" in switch_fields
    assert "related_switch_ids" in review_fields
    assert all(int(row["start_frame"]) <= int(row["end_frame"]) for row in segments)

    switch_ids = {row["switch_id"] for row in switches}
    assert len(switch_ids) == len(switches)
    for review in reviews:
        related_ids = {
            value
            for value in review["related_switch_ids"].split("|")
            if value
        }
        assert related_ids <= switch_ids
        assert review["id_switch_relation"] in {"none", "associated", "caused"}
        if review["id_switch_relation"] == "none":
            assert not related_ids
            assert review["event_error_type"] == "none"
        else:
            assert related_ids
            assert review["event_error_type"] != "none"
    assert any(review["id_switch_relation"] == "caused" for review in reviews)


def test_fall_evaluation_cases_lock_timely_far_and_cause_math():
    payload = _load_json("fall_evaluation_cases.json")

    assert payload["evaluation_protocol_version"] == "phase4_fall_eval_v1"
    for case in payload["timely"]:
        tolerance = round(0.2 * case["fps"])
        timely_window = round(2.0 * case["fps"])
        start = case["fall_start_frame"] - tolerance
        end = case["fall_start_frame"] + timely_window
        timely_frames = [
            frame
            for frame in case["event_frames"]
            if start <= frame <= end
        ]
        early_count = sum(frame < start for frame in case["event_frames"])
        late = not timely_frames and any(
            frame > end for frame in case["event_frames"]
        )
        representative = timely_frames[0] if timely_frames else None
        duplicate = sum(frame >= start for frame in case["event_frames"]) >= 2
        assert representative == case["expected_timely_frame"]
        assert early_count == case["expected_early_false_alarms"]
        assert late is case["expected_late"]
        assert duplicate is case["expected_duplicate"]

    far = payload["far"]
    minutes = sum(
        video["processed_frame_count"] / video["fps"] / 60.0
        for video in far["videos"]
    )
    assert math.isclose(minutes, far["expected_minutes"])
    assert math.isclose(
        far["false_event_count"] / minutes,
        far["expected_far_per_min"],
    )

    cause = payload["cause"]
    assert math.isclose(
        cause["correct_null_count"] / cause["no_candidate_count"],
        cause["expected_null_specificity"],
    )
    assert math.isclose(
        cause["correct_top1_count"] / cause["candidate_count"],
        cause["expected_top1_accuracy"],
    )
    assert math.isclose(
        cause["false_attribution_count"] / cause["evaluable_count"],
        cause["expected_false_attribution_rate"],
    )

    for case in payload["cause_cases"]:
        if case["review_status"] != "reviewed":
            actual = "excluded"
        elif not case["cause_candidate_exists"]:
            actual = (
                "correct_null"
                if case["predicted_cause_actor_id"] is None
                else "false_attribution"
            )
        elif case["predicted_cause_actor_id"] is None:
            actual = "missed_cause"
        elif case["predicted_cause_actor_id"] == case["cause_actor_id"]:
            actual = "correct_top1"
        else:
            actual = "false_attribution"
        assert actual == case["expected"]

    zero = payload["cause_zero_denominator"]
    assert zero["no_candidate_count"] == 0
    assert zero["candidate_count"] == 0
    assert zero["evaluable_count"] == 0
    assert zero["expected_null_specificity"] is None
    assert zero["expected_top1_accuracy"] is None
    assert zero["expected_false_attribution_rate"] is None
    assert zero["evaluation_status"] == "not_evaluable"
