from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import replay_phase4_multiperson_events as replay  # noqa: E402


def _args(tmp_path: Path, config_path: Path) -> argparse.Namespace:
    return argparse.Namespace(
        config=str(config_path),
        fall_model_iou_threshold=0.3,
        fall_model_interval_frames=3,
        fall_pose_normal_gate_enabled=True,
        cache_dir=str(tmp_path / "cache"),
        manifest=str(tmp_path / "manifest.csv"),
        annotations=str(tmp_path / "annotations.csv"),
        selected_profile=str(tmp_path / "selected.json"),
        cache_source_manifest=str(tmp_path / "source_manifest.csv"),
        cache_source_annotations=str(tmp_path / "source_annotations.csv"),
    )


def _selected(config_path: Path) -> dict:
    return {
        "inference": {
            "fall_detector_config_path": str(config_path),
            "fall_detector_config_sha256": replay.contract.sha256_file(config_path),
            "fall_model_iou_threshold": 0.3,
            "fall_model_interval_frames": 3,
            "fall_pose_normal_gate_enabled": True,
        }
    }


def test_rejects_fall_detector_config_sha_mismatch(tmp_path):
    config_path = tmp_path / "fall_detection.json"
    config_path.write_text("{}", encoding="utf-8")
    selected = _selected(config_path)
    selected["inference"]["fall_detector_config_sha256"] = "0" * 64

    with pytest.raises(ValueError, match="config SHA-256"):
        replay._verify_settings_match_selected_profile(
            selected, _args(tmp_path, config_path)
        )


def test_verify_replay_inputs_delegates_full_cache_integrity_check(
    tmp_path, monkeypatch
):
    config_path = tmp_path / "fall_detection.json"
    config_path.write_text("{}", encoding="utf-8")
    args = _args(tmp_path, config_path)
    calls = []

    monkeypatch.setattr(
        replay,
        "verify_cache_integrity",
        lambda **kwargs: calls.append(kwargs),
    )

    replay.verify_replay_inputs(
        args=args,
        selected=_selected(config_path),
        manifest_rows=[{"video_id": "vid"}],
        annotation_rows=[{"video_id": "vid"}],
        video_ids=["vid"],
    )

    assert len(calls) == 1
    assert calls[0]["video_ids"] == ["vid"]
    assert calls[0]["cache_source_manifest_path"] == Path(
        args.cache_source_manifest
    )
    assert calls[0]["cache_source_annotations_path"] == Path(
        args.cache_source_annotations
    )
