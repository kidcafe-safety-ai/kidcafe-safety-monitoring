import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FREEZE_PATH = ROOT / "configs/fall_e1_selected.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _assert_hash_when_available(path_value: str, expected: str) -> None:
    path = ROOT / path_value
    if path.exists():
        assert _sha256(path) == expected


def test_selected_e1_freeze_matches_tracked_configs():
    payload = json.loads(FREEZE_PATH.read_text(encoding="utf-8"))

    assert payload["schema_version"] == "phase4_fall_e1_freeze_v1"
    assert payload["status"] == "selected_for_phase4_target_domain"
    assert payload["default_enabled"] is True
    assert payload["integrity_policy"] == (
        "sha256_fail_closed_before_input_open"
    )

    training = payload["training"]
    training_path = ROOT / training["config_path"]
    assert _sha256(training_path) == training["config_sha256"]
    assert training["workers"] == 1

    inference = payload["inference"]
    detector_config = ROOT / inference["fall_detector_config_path"]
    assert _sha256(detector_config) == inference["fall_detector_config_sha256"]
    assert inference["fall_model_interval_frames"] == 3
    assert inference["fall_pose_normal_gate_enabled"] is True


def test_selected_e1_freeze_keeps_recorded_result_and_scope_explicit():
    payload = json.loads(FREEZE_PATH.read_text(encoding="utf-8"))
    result = payload["results"]["recorded_a03_test"]

    assert result["recall"] == 0.9333333333333333
    assert result["timely_recall"] == 0.9333333333333333
    assert result["false_alarm_per_min"] == 0.0
    assert result["no_fall_exposure_sec"] == 27.2
    assert result["duplicate_events"] == 0
    assert payload["deployment_scope"] == "target_kidcafe_camera"
    assert payload["recorded_dataset"]["recording_protocol"] == (
        "controlled_adult_reenactment"
    )
    assert payload["known_limitations"]


def test_selected_e1_model_matches_hash_when_available():
    payload = json.loads(FREEZE_PATH.read_text(encoding="utf-8"))
    model = payload["model"]
    _assert_hash_when_available(model["path"], model["sha256"])
    _assert_hash_when_available(
        model["source_run_manifest_path"],
        model["source_run_manifest_sha256"],
    )


def test_selected_e1_result_artifacts_match_hashes_when_available():
    payload = json.loads(FREEZE_PATH.read_text(encoding="utf-8"))

    for result in payload["results"].values():
        _assert_hash_when_available(
            result["artifact_path"],
            result["artifact_sha256"],
        )

    recorded_test = payload["results"]["recorded_a03_test"]
    _assert_hash_when_available(
        recorded_test["cache_manifest_path"],
        recorded_test["cache_manifest_sha256"],
    )
