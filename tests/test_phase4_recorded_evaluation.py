from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import cache_fall_signals as cache_signals  # noqa: E402
import evaluate_fall as evaluate  # noqa: E402
import evaluate_fall_from_cache as evaluate_cache  # noqa: E402
import fall_signal_cache as signal_cache  # noqa: E402
import fall_evaluation_protocol as protocol  # noqa: E402
import phase4_recording_contract as contract  # noqa: E402


def _manifest_row(video_id: str, label: str, split: str) -> dict[str, str]:
    scenario = "fall_backward" if label == "fall" else "pick_up"
    return {
        "video_id": video_id,
        "session_id": "S01",
        "actor_ids": "A01",
        "primary_actor_id": "A01",
        "camera_id": "cam01",
        "scenario_type": scenario,
        "label": label,
        "video_path": f"data/{video_id}.mp4",
        "fps": "30",
        "frame_count": "300",
        "width": "1920",
        "height": "1080",
        "lighting": "indoor",
        "split_role": split,
        "review_status": "reviewed",
        "consent_status": "confirmed",
        "checksum_sha256": ("a" if split == "diagnostic" else "b") * 64,
    }


def _write_recorded_inputs(tmp_path: Path) -> tuple[Path, Path]:
    diagnostic_id = "P4_S01_A01_pick_up_01_cam01"
    test_id = "P4_S01_A01_fall_backward_01_cam01"
    manifest_rows = [
        _manifest_row(diagnostic_id, "no_fall", "diagnostic"),
        _manifest_row(test_id, "fall", "test"),
    ]
    annotation_rows = [
        {
            "video_id": diagnostic_id,
            "label": "no_fall",
            "fall_start_frame": "",
            "impact_frame": "",
            "lying_start_frame": "",
            "recovery_frame": "",
            "victim_actor_id": "A01",
            "contact_occurred": "false",
            "cause_candidate_exists": "false",
            "cause_actor_id": "",
            "contact_frame": "",
            "review_status": "reviewed",
            "reviewer_id": "R01",
            "second_reviewer_id": "R02",
            "notes": "",
        },
        {
            "video_id": test_id,
            "label": "fall",
            "fall_start_frame": "80",
            "impact_frame": "90",
            "lying_start_frame": "110",
            "recovery_frame": "180",
            "victim_actor_id": "A01",
            "contact_occurred": "false",
            "cause_candidate_exists": "false",
            "cause_actor_id": "",
            "contact_frame": "",
            "review_status": "reviewed",
            "reviewer_id": "R01",
            "second_reviewer_id": "R02",
            "notes": "",
        },
    ]
    manifest_path = tmp_path / "recordings_manifest.csv"
    annotations_path = tmp_path / "fall_cause_annotations.csv"
    contract.write_csv_atomic(manifest_path, contract.MANIFEST_FIELDS, manifest_rows)
    contract.write_csv_atomic(
        annotations_path, contract.FALL_CAUSE_FIELDS, annotation_rows
    )
    return manifest_path, annotations_path


def test_cache_summary_groups_recorded_metrics_by_primary_actor(tmp_path):
    rows = [
        _manifest_row("P4_S01_A01_fall_backward_01_cam01", "fall", "diagnostic"),
        _manifest_row("P4_S01_A02_pick_up_01_cam01", "no_fall", "diagnostic"),
    ]
    rows[1]["actor_ids"] = "A02"
    rows[1]["primary_actor_id"] = "A02"
    rows[1]["checksum_sha256"] = "c" * 64
    manifest = tmp_path / "recordings_manifest.csv"
    contract.write_csv_atomic(manifest, contract.MANIFEST_FIELDS, rows)

    fall_result = evaluate._VideoResult(
        video_id=rows[0]["video_id"],
        label="fall",
        event_count=1,
        detected=True,
        qualifying_event_count=1,
        timely_detected=True,
        duration_sec=10.0,
    )
    no_fall_result = evaluate._VideoResult(
        video_id=rows[1]["video_id"],
        label="no_fall",
        event_count=1,
        duration_sec=30.0,
    )

    metrics = evaluate_cache.summarize_recorded_primary_actors(
        [fall_result, no_fall_result], manifest, "diagnostic"
    )

    assert metrics["A01"]["recall"] == 1.0
    assert metrics["A01"]["timely_recall"] == 1.0
    assert metrics["A02"]["false_alarm_per_min"] == 2.0


def test_cache_actor_summary_rejects_missing_results(tmp_path):
    rows = [
        _manifest_row("P4_S01_A01_fall_backward_01_cam01", "fall", "diagnostic")
    ]
    manifest = tmp_path / "recordings_manifest.csv"
    contract.write_csv_atomic(manifest, contract.MANIFEST_FIELDS, rows)

    with pytest.raises(ValueError, match="video_id"):
        evaluate_cache.summarize_recorded_primary_actors([], manifest, "diagnostic")


def test_recorded_loader_filters_split_and_joins_video_path(tmp_path):
    manifest, annotations = _write_recorded_inputs(tmp_path)

    rows = evaluate.load_recorded_annotations(
        annotations, manifest, "diagnostic", include_unreviewed=False
    )

    assert len(rows) == 1
    assert rows[0].video_id == "P4_S01_A01_pick_up_01_cam01"
    assert rows[0].video_path == "data/P4_S01_A01_pick_up_01_cam01.mp4"
    assert rows[0].label == "no_fall"


def test_recorded_test_split_is_sealed_by_default(tmp_path):
    manifest, annotations = _write_recorded_inputs(tmp_path)
    rows = evaluate.load_recorded_annotations(
        annotations, manifest, "test", include_unreviewed=False
    )

    with pytest.raises(SystemExit, match="split test"):
        evaluate.guard_holdout(tmp_path, "test", rows, allow_holdout=False)

    evaluate.guard_holdout(tmp_path, "test", rows, allow_holdout=True)


def test_official_recorded_protocol_builds_and_checks_dataset_provenance(tmp_path):
    manifest, annotations = _write_recorded_inputs(tmp_path)

    schema = protocol.validate_protocol_request(
        protocol.EVALUATION_PROTOCOL_VERSION,
        annotations,
        protocol.EARLY_TOLERANCE_SEC,
        protocol.TIMELY_WINDOW_SEC,
        False,
        recordings_manifest_path=manifest,
        split="diagnostic",
    )
    provenance = protocol.build_dataset_provenance(
        annotation_schema_version=schema,
        annotations_path=annotations,
        recordings_manifest_path=manifest,
        split="diagnostic",
        video_count=1,
    )
    cache_manifest = {
        "tracker": {
            "model_sha256": "b" * 64,
            "resolved_device": "mps",
        },
        "auxiliary_model": {
            "model_sha256": "c" * 64,
            "resolved_device": "mps",
        },
        "dataset": provenance,
    }

    assert schema == protocol.PHASE4_RECORDED_ANNOTATION_VERSION
    assert provenance["annotations_sha256"] == protocol.sha256_file(annotations)
    assert provenance["recordings_manifest_sha256"] == protocol.sha256_file(manifest)
    protocol.validate_official_cache_manifest(cache_manifest, provenance)

    changed = {**provenance, "annotations_sha256": "d" * 64}
    with pytest.raises(ValueError, match="dataset provenance"):
        protocol.validate_official_cache_manifest(cache_manifest, changed)


def test_recorded_metadata_requires_and_records_dataset_provenance(
    tmp_path, monkeypatch
):
    manifest, annotations = _write_recorded_inputs(tmp_path)
    config = tmp_path / "fall.json"
    config.write_text("{}", encoding="utf-8")
    provenance = protocol.build_dataset_provenance(
        annotation_schema_version=protocol.PHASE4_RECORDED_ANNOTATION_VERSION,
        annotations_path=annotations,
        recordings_manifest_path=manifest,
        split="diagnostic",
        video_count=1,
    )
    monkeypatch.setattr(protocol, "_git_state", lambda: ("1" * 40, False))

    metadata = protocol.build_metadata(
        annotation_schema_version=protocol.PHASE4_RECORDED_ANNOTATION_VERSION,
        model_sha256="a" * 64,
        config_path=config,
        tracker="pose",
        tracker_config={"model_sha256": "b" * 64},
        device={"tracker": "mps", "auxiliary_model": "mps"},
        dataset_provenance=provenance,
    )

    assert metadata["dataset"] == provenance
    assert metadata["annotation_schema_version"] == "phase4_fall_cause_v1"


def test_recorded_cache_main_writes_dataset_provenance(tmp_path, monkeypatch):
    manifest, annotations = _write_recorded_inputs(tmp_path)
    cache_dir = tmp_path / "cache"
    tracker_model = tmp_path / "pose.pt"
    fall_model = tmp_path / "fall.pt"
    tracker_model.write_bytes(b"pose")
    fall_model.write_bytes(b"fall")

    class DummyProvider:
        def __init__(self, **_kwargs):
            self._device = "mps"

    monkeypatch.setattr(cache_signals, "PoseTracker", DummyProvider)
    monkeypatch.setattr(cache_signals, "AuxiliaryFallModel", DummyProvider)
    monkeypatch.setattr(
        cache_signals,
        "_cache_one_video",
        lambda *_args, **_kwargs: {"frame_count": 1, "elapsed_sec": 1.0},
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "cache_fall_signals.py",
            "--annotations",
            str(annotations),
            "--recordings-manifest",
            str(manifest),
            "--videos-dir",
            str(tmp_path),
            "--split",
            "diagnostic",
            "--model",
            str(tracker_model),
            "--device",
            "mps",
            "--fall-model-path",
            str(fall_model),
            "--fall-model-device",
            "mps",
            "--cache-dir",
            str(cache_dir),
            "--evaluation-protocol-version",
            protocol.EVALUATION_PROTOCOL_VERSION,
        ],
    )

    cache_signals.main()

    cache_manifest = signal_cache.read_manifest(cache_dir)
    assert cache_manifest is not None
    assert cache_manifest["split"] == "diagnostic"
    assert cache_manifest["dataset"] == protocol.build_dataset_provenance(
        annotation_schema_version=protocol.PHASE4_RECORDED_ANNOTATION_VERSION,
        annotations_path=annotations,
        recordings_manifest_path=manifest,
        split="diagnostic",
        video_count=1,
    )
