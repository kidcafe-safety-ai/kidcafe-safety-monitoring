from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import run_phase4_tracker_arm as runner  # noqa: E402


REPO_ROOT = Path(__file__).resolve().parent.parent


def _config():
    config = json.loads(
        (REPO_ROOT / "configs/phase4_tracker_comparison.json").read_text(
            encoding="utf-8"
        )
    )
    config["_config_path"] = "configs/phase4_tracker_comparison.json"
    return config


def test_reid_arm_command_pins_tracker_and_reid_hashes(tmp_path):
    config = _config()
    arm = copy.deepcopy(config["arms"][2])

    artifacts, commands = runner.build_commands(
        config=config,
        arm=arm,
        repo_root=REPO_ROOT,
        output_root=tmp_path,
        device="mps",
        fall_model_device="mps",
        force=False,
    )

    cache_command = commands[0]
    assert cache_command[cache_command.index("--tracker-config") + 1] == arm[
        "tracker_config_path"
    ]
    assert cache_command[cache_command.index("--tracker-config-sha256") + 1] == arm[
        "tracker_config_sha256"
    ]
    assert cache_command[cache_command.index("--reid-model-sha256") + 1] == arm[
        "reid_model_sha256"
    ]
    assert artifacts["cache_dir"] == tmp_path / "arms" / arm["arm_id"] / "cache"


def test_non_reid_arm_command_does_not_accept_reid_hash(tmp_path):
    config = _config()
    arm = copy.deepcopy(config["arms"][1])

    _, commands = runner.build_commands(
        config=config,
        arm=arm,
        repo_root=REPO_ROOT,
        output_root=tmp_path,
        device="cpu",
        fall_model_device="cpu",
        force=True,
    )

    assert "--reid-model-sha256" not in commands[0]
    assert "--force" in commands[0]
    assert "--force" in commands[-1]


def test_arm_pipeline_keeps_same_cache_for_eval_and_both_replays(tmp_path):
    config = _config()
    arm = copy.deepcopy(config["arms"][0])

    artifacts, commands = runner.build_commands(
        config=config,
        arm=arm,
        repo_root=REPO_ROOT,
        output_root=tmp_path,
        device="cpu",
        fall_model_device="cpu",
        force=False,
    )

    expected = str(artifacts["cache_dir"])
    for command in commands[:4]:
        assert command[command.index("--cache-dir") + 1] == expected


def test_installed_ultralytics_version_matches_frozen_config():
    config = _config()

    assert runner.installed_ultralytics_version() == config["ultralytics_version"]
