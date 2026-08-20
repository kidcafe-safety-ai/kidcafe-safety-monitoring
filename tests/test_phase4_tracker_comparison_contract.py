from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import phase4_recording_contract as recording_contract  # noqa: E402
import phase4_tracker_comparison_contract as contract  # noqa: E402


REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = REPO_ROOT / "configs/phase4_tracker_comparison.json"
BUFFER60_CONFIG_PATH = (
    REPO_ROOT / "configs/phase4_tracker_buffer60_comparison.json"
)


def test_repository_comparison_contract_and_cohort_are_valid():
    config = contract.load_config(CONFIG_PATH, repo_root=REPO_ROOT)
    manifest_rows = recording_contract.load_recordings_manifest(
        REPO_ROOT / config["dataset"]["manifest_path"]
    )
    annotation_rows = recording_contract.load_fall_cause_annotations(
        REPO_ROOT / config["dataset"]["annotations_path"], manifest_rows
    )

    contract.validate_cohort(config, manifest_rows, annotation_rows)


def test_repository_arm_order_is_frozen():
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    assert tuple(arm["arm_id"] for arm in config["arms"]) == contract.ARM_IDS


@pytest.mark.parametrize(
    ("config_path", "expected_buffer"),
    (
        (CONFIG_PATH, 30),
        (BUFFER60_CONFIG_PATH, 60),
    ),
)
def test_repository_tracker_buffer_variants_are_frozen(
    config_path, expected_buffer
):
    config = contract.load_config(config_path, repo_root=REPO_ROOT)

    for arm in config["arms"]:
        tracker_path = REPO_ROOT / arm["tracker_config_path"]
        tracker_config = yaml.safe_load(tracker_path.read_text(encoding="utf-8"))
        assert tracker_config["track_buffer"] == expected_buffer


def test_reid_arm_rejects_auto_model(tmp_path):
    tracker_config = tmp_path / "botsort.yaml"
    tracker_config.write_text(
        "tracker_type: botsort\nwith_reid: true\nmodel: auto\n",
        encoding="utf-8",
    )
    arm = {
        "arm_id": "botsort_with_reid",
        "tracker_config_path": tracker_config.name,
        "tracker_config_sha256": contract.sha256_file(tracker_config),
        "tracker_backend": "botsort",
        "with_reid": True,
        "reid_model_path": "auto",
        "reid_model_sha256": "0" * 64,
    }

    errors = contract._validate_arm(
        arm, repo_root=tmp_path, require_model_artifacts=True
    )

    assert any("자동 다운로드" in error for error in errors)


def test_cache_arm_rejects_wrong_tracker_yaml_hash():
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    arm = copy.deepcopy(config["arms"][1])
    cache_manifest = {
        "tracker": {
            **contract.arm_provenance(arm),
            "tracker_config": arm["tracker_config_path"],
        }
    }
    cache_manifest["tracker"].pop("arm_id")
    cache_manifest["tracker"].pop("arm_config_sha256")
    cache_manifest["tracker"]["tracker_config_sha256"] = "f" * 64

    with pytest.raises(ValueError, match="cache provenance"):
        contract.validate_cache_arm(cache_manifest, arm)


def test_fixed_inference_rejects_selected_profile_drift():
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    selected = json.loads(
        (REPO_ROOT / config["selected_profile"]["path"]).read_text(encoding="utf-8")
    )
    selected["inference"]["fall_model_interval_frames"] = 99

    errors = contract._validate_fixed_inference(config, selected)

    assert any("fall_model_interval_frames" in error for error in errors)
