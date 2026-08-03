"""Phase 4 공식 낙상 평가 protocol과 provenance 회귀 테스트."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import fall_evaluation_protocol as protocol


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "phase4_contract"


def _write_annotations(path: Path, v2: bool = True) -> None:
    optional = ",dataset_fall_label_frame" if v2 else ""
    value = ",10" if v2 else ""
    path.write_text(
        "video_id,label,video_path,fall_start_frame,impact_frame,lying_start_frame,"
        f"review_status{optional}\n"
        f"v1,fall,v1.avi,10,12,15,reviewed{value}\n",
        encoding="utf-8",
    )


def _write_v2_row(path: Path, **overrides) -> None:
    values = {
        "video_id": "v1",
        "label": "fall",
        "video_path": "v1.avi",
        "dataset_fall_label_frame": "10",
        "fall_start_frame": "8",
        "impact_frame": "10",
        "lying_start_frame": "15",
        "review_status": "reviewed",
    }
    values.update(overrides)
    columns = [
        "video_id",
        "label",
        "video_path",
        "dataset_fall_label_frame",
        "fall_start_frame",
        "impact_frame",
        "lying_start_frame",
        "review_status",
    ]
    path.write_text(
        ",".join(columns) + "\n" + ",".join(str(values[column]) for column in columns) + "\n",
        encoding="utf-8",
    )


def _official_manifest() -> dict:
    return {
        "tracker": {
            "tracker_type": "pose",
            "model_sha256": "b" * 64,
            "resolved_device": "mps",
        },
        "auxiliary_model": {
            "model_sha256": "a" * 64,
            "resolved_device": "mps",
        },
    }


def test_protocol_constants_match_contract_manifest():
    payload = json.loads((FIXTURE_DIR / "contract_manifest.json").read_text())

    assert protocol.CONTRACT_VERSION == payload["contract_version"]
    assert protocol.EVALUATION_PROTOCOL_VERSION == payload["evaluation_protocol_version"]
    assert protocol.EVENT_MATCHING_RULE == payload["evaluation_rule_ids"]["event_matching_rule"]
    assert protocol.DUPLICATE_RULE == payload["evaluation_rule_ids"]["duplicate_rule"]
    assert protocol.FAR_DENOMINATOR_RULE == payload["evaluation_rule_ids"][
        "far_denominator_rule"
    ]


def test_official_protocol_accepts_reviewed_v2_annotations(tmp_path):
    annotations = tmp_path / "annotations_v2.csv"
    _write_annotations(annotations, v2=True)

    result = protocol.validate_protocol_request(
        protocol.EVALUATION_PROTOCOL_VERSION,
        annotations,
        early_tolerance_sec=0.2,
        timely_window_sec=2.0,
        include_unreviewed=False,
    )

    assert result == protocol.CAUCAFALL_ANNOTATION_VERSION


@pytest.mark.parametrize(
    ("early_tolerance_sec", "timely_window_sec", "include_unreviewed", "message"),
    [
        (0.1, 2.0, False, "early_tolerance_sec"),
        (0.2, 2.1, False, "timely_window_sec"),
        (0.2, 2.0, True, "reviewed"),
    ],
)
def test_official_protocol_rejects_rule_overrides(
    tmp_path,
    early_tolerance_sec,
    timely_window_sec,
    include_unreviewed,
    message,
):
    annotations = tmp_path / "annotations_v2.csv"
    _write_annotations(annotations, v2=True)

    with pytest.raises(ValueError, match=message):
        protocol.validate_protocol_request(
            protocol.EVALUATION_PROTOCOL_VERSION,
            annotations,
            early_tolerance_sec,
            timely_window_sec,
            include_unreviewed,
        )


def test_official_protocol_rejects_v1_annotations(tmp_path):
    annotations = tmp_path / "annotations_v1.csv"
    _write_annotations(annotations, v2=False)

    with pytest.raises(ValueError, match="caucafall_annotation_v2"):
        protocol.validate_protocol_request(
            protocol.EVALUATION_PROTOCOL_VERSION,
            annotations,
            early_tolerance_sec=0.2,
            timely_window_sec=2.0,
            include_unreviewed=False,
        )


@pytest.mark.parametrize(
    "missing_column",
    [
        "dataset_fall_label_frame",
        "fall_start_frame",
        "impact_frame",
        "lying_start_frame",
    ],
)
def test_official_protocol_rejects_incomplete_reviewed_fall(tmp_path, missing_column):
    annotations = tmp_path / "annotations_v2.csv"
    _write_v2_row(annotations, **{missing_column: ""})

    with pytest.raises(ValueError, match=missing_column):
        protocol.validate_protocol_request(
            protocol.EVALUATION_PROTOCOL_VERSION,
            annotations,
            early_tolerance_sec=0.2,
            timely_window_sec=2.0,
            include_unreviewed=False,
        )


@pytest.mark.parametrize("review_status", ["", "done", "REVIEWED"])
def test_official_protocol_rejects_unknown_status_before_filtering(
    tmp_path, review_status
):
    annotations = tmp_path / "annotations_v2.csv"
    _write_v2_row(annotations, review_status=review_status)

    with pytest.raises(ValueError, match="review_status"):
        protocol.validate_protocol_request(
            protocol.EVALUATION_PROTOCOL_VERSION,
            annotations,
            early_tolerance_sec=0.2,
            timely_window_sec=2.0,
            include_unreviewed=False,
        )


def test_official_protocol_allows_incomplete_pending_fall_but_does_not_score_it(tmp_path):
    annotations = tmp_path / "annotations_v2.csv"
    _write_v2_row(
        annotations,
        dataset_fall_label_frame="",
        fall_start_frame="",
        impact_frame="",
        lying_start_frame="",
        review_status="pending",
    )

    assert protocol.validate_protocol_request(
        protocol.EVALUATION_PROTOCOL_VERSION,
        annotations,
        early_tolerance_sec=0.2,
        timely_window_sec=2.0,
        include_unreviewed=False,
    ) == protocol.CAUCAFALL_ANNOTATION_VERSION


@pytest.mark.parametrize("review_status", ["pending", "needs_review"])
def test_official_protocol_rejects_out_of_order_unreviewed_fall_frames(
    tmp_path, review_status
):
    annotations = tmp_path / "annotations_v2.csv"
    _write_v2_row(
        annotations,
        fall_start_frame="20",
        impact_frame="",
        lying_start_frame="10",
        review_status=review_status,
    )

    with pytest.raises(ValueError, match="fall_start_frame"):
        protocol.validate_protocol_request(
            protocol.EVALUATION_PROTOCOL_VERSION,
            annotations,
            early_tolerance_sec=0.2,
            timely_window_sec=2.0,
            include_unreviewed=False,
        )


def test_official_protocol_validates_unreviewed_rows_and_duplicate_ids(tmp_path):
    annotations = tmp_path / "annotations_v2.csv"
    header = (
        "video_id,label,video_path,dataset_fall_label_frame,fall_start_frame,"
        "impact_frame,lying_start_frame,review_status\n"
    )
    annotations.write_text(
        header
        + "v1,no_fall,v1.avi,,not-an-int,,,pending\n"
        + "v1,no_fall,v2.avi,,,,,needs_review\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError) as exc_info:
        protocol.validate_protocol_request(
            protocol.EVALUATION_PROTOCOL_VERSION,
            annotations,
            early_tolerance_sec=0.2,
            timely_window_sec=2.0,
            include_unreviewed=False,
        )

    assert "정수" in str(exc_info.value)
    assert "중복된 video_id" in str(exc_info.value)


def test_legacy_evaluation_does_not_require_v2_annotations(tmp_path):
    annotations = tmp_path / "annotations_v1.csv"
    _write_annotations(annotations, v2=False)

    assert protocol.validate_protocol_request(None, annotations, 0.0, 3.0, True) is None


def test_official_cache_manifest_requires_model_hash_and_resolved_devices():
    protocol.validate_official_cache_manifest(_official_manifest())

    missing_device = _official_manifest()
    missing_device["tracker"].pop("resolved_device")
    with pytest.raises(ValueError, match="tracker.resolved_device"):
        protocol.validate_official_cache_manifest(missing_device)

    missing_tracker_hash = _official_manifest()
    missing_tracker_hash["tracker"].pop("model_sha256")
    with pytest.raises(ValueError, match="tracker.model_sha256"):
        protocol.validate_official_cache_manifest(missing_tracker_hash)

    missing_hash = _official_manifest()
    missing_hash["auxiliary_model"]["model_sha256"] = None
    with pytest.raises(ValueError, match="auxiliary_model.model_sha256"):
        protocol.validate_official_cache_manifest(missing_hash)

    unresolved_device = _official_manifest()
    unresolved_device["auxiliary_model"]["resolved_device"] = "auto"
    with pytest.raises(ValueError, match="auxiliary_model.resolved_device"):
        protocol.validate_official_cache_manifest(unresolved_device)


@pytest.mark.parametrize("device", ["", "   ", "auto", " AUTO ", 1, True, None])
def test_official_cache_manifest_rejects_non_device_values(device):
    manifest = _official_manifest()
    manifest["tracker"]["resolved_device"] = device

    with pytest.raises(ValueError, match="tracker.resolved_device"):
        protocol.validate_official_cache_manifest(manifest)


def test_normalize_resolved_device_strips_whitespace():
    assert protocol.normalize_resolved_device(" mps ", "tracker") == "mps"


@pytest.mark.parametrize("device", ["", "   ", "auto", " AUTO ", 1, None])
def test_normalize_resolved_device_rejects_unknown_values(device):
    with pytest.raises(ValueError, match="tracker"):
        protocol.normalize_resolved_device(device, "tracker")


def test_build_metadata_records_hashes_rules_and_git_state(tmp_path):
    model = tmp_path / "model.pt"
    config = tmp_path / "config.json"
    model.write_bytes(b"model")
    config.write_text("{}", encoding="utf-8")

    payload = protocol.build_metadata(
        annotation_schema_version=protocol.CAUCAFALL_ANNOTATION_VERSION,
        model_sha256=protocol.sha256_file(model),
        config_path=config,
        tracker="pose",
        tracker_config={"tracker_type": "pose", "model_sha256": "b" * 64},
        device={"tracker": "mps", "auxiliary_model": "mps", "evaluation": "live"},
        evaluator_git_commit="1" * 40,
        evaluator_git_dirty=False,
    )

    assert payload["contract_version"] == protocol.CONTRACT_VERSION
    assert payload["evaluation_protocol_version"] == protocol.EVALUATION_PROTOCOL_VERSION
    assert payload["model_sha256"] == protocol.sha256_file(model)
    assert payload["config_sha256"] == protocol.sha256_file(config)
    assert payload["evaluator_git_commit"] == "1" * 40
    assert payload["evaluator_git_dirty"] is False
    assert payload["early_tolerance_sec"] == 0.2
    assert payload["timely_window_sec"] == 2.0


def test_build_metadata_normalizes_resolved_device_whitespace(tmp_path):
    config = tmp_path / "config.json"
    config.write_text("{}", encoding="utf-8")

    payload = protocol.build_metadata(
        annotation_schema_version=protocol.CAUCAFALL_ANNOTATION_VERSION,
        model_sha256="a" * 64,
        config_path=config,
        tracker="pose",
        tracker_config={"tracker_type": "pose", "model_sha256": "b" * 64},
        device={"tracker": " mps ", "auxiliary_model": " cpu ", "evaluation": "cache"},
        evaluator_git_commit="1" * 40,
        evaluator_git_dirty=False,
    )

    assert payload["device"]["tracker"] == "mps"
    assert payload["device"]["auxiliary_model"] == "cpu"


def test_build_metadata_rejects_unresolved_device_and_invalid_git_commit(tmp_path):
    config = tmp_path / "config.json"
    config.write_text("{}", encoding="utf-8")
    common = {
        "annotation_schema_version": protocol.CAUCAFALL_ANNOTATION_VERSION,
        "model_sha256": "a" * 64,
        "config_path": config,
        "tracker": "pose",
        "tracker_config": {"tracker_type": "pose", "model_sha256": "b" * 64},
        "evaluator_git_dirty": False,
    }

    with pytest.raises(ValueError, match="tracker inference device"):
        protocol.build_metadata(
            **common,
            device={"tracker": "auto", "auxiliary_model": "mps"},
            evaluator_git_commit="1" * 40,
        )

    with pytest.raises(ValueError, match="device metadata object"):
        protocol.build_metadata(
            **common,
            device=None,
            evaluator_git_commit="1" * 40,
        )

    with pytest.raises(ValueError, match="40자리 evaluator Git commit"):
        protocol.build_metadata(
            **common,
            device={"tracker": "mps", "auxiliary_model": "mps"},
            evaluator_git_commit="not-a-commit",
        )
