"""scripts/evaluate_fall_from_cache.py의 검증·재생 wiring 테스트.

metadata 검증과 최소 cache main() 경로를 실제 cv2/YOLO 추론 없이 확인한다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import evaluate_fall as ef  # noqa: E402
import evaluate_fall_from_cache as efc  # noqa: E402

from src.common.types import Track, TrackingResult  # noqa: E402
from src.safety.auxiliary_fall_model import FallDetection  # noqa: E402
from src.safety.fall_detector import FallDetectorConfig  # noqa: E402
from src.safety.fall_model_matching import match_detections_to_tracks  # noqa: E402
from src.safety.fall_pipeline import FallPipeline  # noqa: E402

_TRACKER_META = {
    "tracker_type": "pose",
    "model_path": "yolo26n-pose.pt",
    "model_sha256": "abc",
    "conf": 0.5,
    "tracker_config": "bytetrack.yaml",
    "tracker_config_sha256": None,
    "requested_device": "auto",
    "resolved_device": "mps",
}


def test_cache_protocol_metadata_uses_manifest_provenance(tmp_path, monkeypatch):
    config = tmp_path / "fall.json"
    config.write_text("{}", encoding="utf-8")
    manifest = {
        "tracker": {**_TRACKER_META, "model_sha256": "b" * 64},
        "auxiliary_model": {
            "model_path": "fall.pt",
            "model_sha256": "a" * 64,
            "conf": 0.5,
            "requested_device": "auto",
            "resolved_device": "mps",
        },
    }
    monkeypatch.setattr(
        efc.evaluation_protocol,
        "_git_state",
        lambda: ("1" * 40, False),
    )

    payload = efc._build_cache_protocol_metadata(
        SimpleNamespace(config=str(config)),
        efc.evaluation_protocol.CAUCAFALL_ANNOTATION_VERSION,
        manifest,
    )

    assert payload["model_sha256"] == "a" * 64
    assert payload["tracker_config"] == manifest["tracker"]
    assert payload["device"] == {
        "tracker": "mps",
        "auxiliary_model": "mps",
        "evaluation": "cache_replay",
    }


def _row(**overrides) -> ef._AnnotationRow:
    defaults = dict(
        video_id="v1",
        label="no_fall",
        video_path="v1.avi",
        fall_start_frame=None,
        impact_frame=None,
        lying_start_frame=None,
        review_status="reviewed",
    )
    defaults.update(overrides)
    return ef._AnnotationRow(**defaults)


def _manifest(**overrides) -> dict:
    defaults = dict(
        cache_schema_version=1,
        split="development",
        videos_dir="/data/development",
        tracker=_TRACKER_META,
        auxiliary_model=None,
    )
    defaults.update(overrides)
    return defaults


def _metadata(**overrides) -> dict:
    defaults = dict(
        cache_schema_version=1,
        video_id="v1",
        video_path="/data/development/v1.avi",
        video_size_bytes=None,
        fps=20.0,
        frame_count=1,
        tracker=_TRACKER_META,
        auxiliary_model=None,
    )
    defaults.update(overrides)
    return defaults


def _write_cache_cli_fixture(tmp_path: Path, official: bool) -> dict:
    annotations = tmp_path / "annotations_v2.csv"
    annotations.write_text(
        "video_id,label,video_path,dataset_fall_label_frame,fall_start_frame,"
        "impact_frame,lying_start_frame,review_status\n"
        "v1,no_fall,v1.avi,,,,,reviewed\n",
        encoding="utf-8",
    )
    config = tmp_path / "fall.json"
    config.write_text("{}", encoding="utf-8")
    selected_profile = tmp_path / "selected.json"
    selected_profile.write_text(
        json.dumps(
            {
                "schema_version": "selected_v1",
                "model": {},
                "inference": {},
                "recorded_dataset": {},
                "evaluation_protocol": {},
                "results": {},
            }
        ),
        encoding="utf-8",
    )
    videos_dir = tmp_path / "videos"
    videos_dir.mkdir()
    video_path = videos_dir / "v1.avi"
    video_path.write_bytes(b"video")
    cache_dir = tmp_path / "cache"

    tracker_meta = {
        **_TRACKER_META,
        "model_sha256": "b" * 64,
    }
    auxiliary_meta = {
        "model_path": "fall.pt",
        "model_sha256": "a" * 64,
        "conf": 0.5,
        "requested_device": "auto",
        "resolved_device": "cpu",
    }
    if not official:
        tracker_meta.pop("requested_device")
        tracker_meta.pop("resolved_device")
        auxiliary_meta.pop("requested_device")
        auxiliary_meta.pop("resolved_device")

    manifest = efc.cache.build_manifest(
        split="development",
        videos_dir=str(videos_dir.resolve()),
        tracker_meta=tracker_meta,
        auxiliary_meta=auxiliary_meta,
    )
    efc.cache.write_manifest(cache_dir, manifest)
    efc.cache.write_video_cache(
        efc.cache.cache_path_for(cache_dir, "v1"),
        video_id="v1",
        fps=20.0,
        tracker_meta=tracker_meta,
        auxiliary_meta=auxiliary_meta,
        frames=[efc.cache.CachedFrame(0, "00:00:00.000", [], [])],
        video_path=str(video_path.resolve()),
        video_size_bytes=video_path.stat().st_size,
    )
    return {
        "annotations": annotations,
        "config": config,
        "selected_profile": selected_profile,
        "cache_dir": cache_dir,
        "output": tmp_path / "result.json",
    }


def _run_cache_cli(monkeypatch, paths: dict, official: bool) -> None:
    argv = [
        "evaluate_fall_from_cache.py",
        "--annotations",
        str(paths["annotations"]),
        "--cache-dir",
        str(paths["cache_dir"]),
        "--split",
        "development",
        "--config",
        str(paths["config"]),
        "--output",
        str(paths["output"]),
    ]
    if official:
        argv.extend(
            [
                "--evaluation-protocol-version",
                efc.evaluation_protocol.EVALUATION_PROTOCOL_VERSION,
                "--selected-profile",
                str(paths["selected_profile"]),
            ]
        )
    monkeypatch.setattr(sys, "argv", argv)
    monkeypatch.setattr(
        efc.evaluation_protocol,
        "_git_state",
        lambda: ("1" * 40, False),
    )
    efc.main()


def test_official_cache_cli_rejects_legacy_manifest(tmp_path, monkeypatch):
    paths = _write_cache_cli_fixture(tmp_path, official=False)

    with pytest.raises(SystemExit, match="cache provenance"):
        _run_cache_cli(monkeypatch, paths, official=True)

    assert not paths["output"].exists()


def test_non_official_cache_cli_accepts_legacy_manifest(tmp_path, monkeypatch):
    paths = _write_cache_cli_fixture(tmp_path, official=False)

    _run_cache_cli(monkeypatch, paths, official=False)

    payload = json.loads(paths["output"].read_text(encoding="utf-8"))
    assert payload["evaluation_valid"] is True
    assert "evaluation_protocol_version" not in payload


def test_official_cache_cli_writes_provenance_to_result_root(tmp_path, monkeypatch):
    paths = _write_cache_cli_fixture(tmp_path, official=True)

    _run_cache_cli(monkeypatch, paths, official=True)

    payload = json.loads(paths["output"].read_text(encoding="utf-8"))
    assert payload["evaluation_valid"] is True
    assert payload["skipped_with_error"] == 0
    assert payload["contract_version"] == efc.evaluation_protocol.CONTRACT_VERSION
    assert payload["evaluation_protocol_version"] == (
        efc.evaluation_protocol.EVALUATION_PROTOCOL_VERSION
    )
    assert payload["annotation_schema_version"] == (
        efc.evaluation_protocol.CAUCAFALL_ANNOTATION_VERSION
    )
    assert payload["evaluator_git_commit"] == "1" * 40
    assert payload["evaluator_git_dirty"] is False
    assert payload["model_sha256"] == "a" * 64
    assert payload["config_sha256"] == efc.evaluation_protocol.sha256_file(
        paths["config"]
    )
    assert payload["tracker_config"]["model_sha256"] == "b" * 64
    assert payload["device"]["tracker"] == "mps"
    assert payload["device"]["auxiliary_model"] == "cpu"
    assert payload["device"]["evaluation"] == "cache_replay"
    assert payload["early_tolerance_sec"] == 0.2
    assert payload["timely_window_sec"] == 2.0
    assert payload["event_matching_rule"] == efc.evaluation_protocol.EVENT_MATCHING_RULE
    assert payload["duplicate_rule"] == efc.evaluation_protocol.DUPLICATE_RULE
    assert payload["far_denominator_rule"] == (
        efc.evaluation_protocol.FAR_DENOMINATOR_RULE
    )
    assert payload["cache_manifest_sha256"] == efc.recording_contract.sha256_file(
        paths["cache_dir"] / "manifest.json"
    )
    selected_profile = json.loads(paths["selected_profile"].read_text(encoding="utf-8"))
    assert payload["selected_execution_profile_sha256"] == (
        efc.recording_contract.selected_execution_profile_sha256(selected_profile)
    )
    assert payload["cache_dataset_revision_verification"] == (
        "exact_dataset_revision"
    )


def test_official_cache_accepts_history_only_when_evaluated_rows_match(monkeypatch):
    args = SimpleNamespace(
        recordings_manifest="current_manifest.csv",
        annotations="current_annotations.csv",
        selected_profile="selected.json",
        cache_source_manifest="source_manifest.csv",
        cache_source_annotations="source_annotations.csv",
        cache_dir="cache",
    )
    manifest = {"dataset": {"annotations_sha256": "old"}}
    validation_calls = []

    def validate(manifest_arg, expected_dataset_provenance=None):
        validation_calls.append(expected_dataset_provenance)
        if expected_dataset_provenance is not None:
            raise ValueError("dataset mismatch")

    monkeypatch.setattr(
        efc.evaluation_protocol, "validate_official_cache_manifest", validate
    )
    monkeypatch.setattr(
        efc.recording_contract,
        "load_recordings_manifest",
        lambda path: [{"video_id": "v1"}],
    )
    monkeypatch.setattr(
        efc.recording_contract,
        "load_fall_cause_annotations",
        lambda path, manifest_rows: [{"video_id": "v1"}],
    )
    verify = MagicMock()
    monkeypatch.setattr(efc, "verify_cache_integrity", verify)

    result = efc._validate_official_cache_dataset(
        args=args,
        manifest=manifest,
        expected_dataset_provenance={"annotations_sha256": "current"},
        evaluated_video_ids=["v1"],
    )

    assert result == "history_snapshot_matching_evaluated_rows_v1"
    assert validation_calls == [
        {"annotations_sha256": "current"},
        None,
    ]
    verify.assert_called_once()


def test_official_cache_rejects_mismatch_without_history_inputs(monkeypatch):
    args = SimpleNamespace(
        recordings_manifest="current_manifest.csv",
        selected_profile="selected.json",
        cache_source_manifest=None,
        cache_source_annotations=None,
    )
    monkeypatch.setattr(
        efc.evaluation_protocol,
        "validate_official_cache_manifest",
        MagicMock(side_effect=ValueError("dataset mismatch")),
    )

    with pytest.raises(ValueError, match="dataset mismatch"):
        efc._validate_official_cache_dataset(
            args=args,
            manifest={},
            expected_dataset_provenance={"annotations_sha256": "current"},
            evaluated_video_ids=["v1"],
        )


class TestValidateCacheMetadata:
    def test_matching_metadata_returns_none(self):
        row = _row()
        manifest = _manifest()
        metadata = _metadata()

        result = efc._validate_cache_metadata(metadata, manifest, row, Path("/data/development"))

        assert result is None

    def test_tracker_mismatch_is_rejected(self):
        row = _row()
        manifest = _manifest()
        metadata = _metadata(tracker={**_TRACKER_META, "conf": 0.99})

        result = efc._validate_cache_metadata(metadata, manifest, row, Path("/data/development"))

        assert result is not None
        assert "tracker" in result

    def test_auxiliary_model_mismatch_is_rejected(self):
        row = _row()
        manifest = _manifest(auxiliary_model=None)
        metadata = _metadata(
            auxiliary_model={"model_path": "fall_detector_v1.pt", "model_sha256": "x", "conf": 0.5}
        )

        result = efc._validate_cache_metadata(metadata, manifest, row, Path("/data/development"))

        assert result is not None
        assert "auxiliary_model" in result

    def test_video_path_mismatch_is_rejected(self):
        row = _row()
        manifest = _manifest()
        metadata = _metadata(video_path="/data/development/some_other_video.avi")

        result = efc._validate_cache_metadata(metadata, manifest, row, Path("/data/development"))

        assert result is not None
        assert "video_path" in result

    def test_video_path_none_is_not_rejected(self):
        """video_path를 기록하지 않은(구버전) 캐시는 이 검증을 그냥 통과시킨다."""
        row = _row()
        manifest = _manifest()
        metadata = _metadata(video_path=None)

        result = efc._validate_cache_metadata(metadata, manifest, row, Path("/data/development"))

        assert result is None

    def test_video_size_mismatch_is_rejected(self, tmp_path):
        video_file = tmp_path / "v1.avi"
        video_file.write_bytes(b"x" * 100)
        row = _row(video_path="v1.avi")
        manifest = _manifest(videos_dir=str(tmp_path))
        metadata = _metadata(video_path=str(video_file), video_size_bytes=999)

        result = efc._validate_cache_metadata(metadata, manifest, row, tmp_path)

        assert result is not None
        assert "크기" in result

    def test_video_size_match_is_not_rejected(self, tmp_path):
        video_file = tmp_path / "v1.avi"
        video_file.write_bytes(b"x" * 100)
        row = _row(video_path="v1.avi")
        manifest = _manifest(videos_dir=str(tmp_path))
        metadata = _metadata(video_path=str(video_file), video_size_bytes=100)

        result = efc._validate_cache_metadata(metadata, manifest, row, tmp_path)

        assert result is None


def _tracking_result(frame_number, track_id=1) -> TrackingResult:
    return TrackingResult(
        frame_number=frame_number,
        timestamp="00:00:00.000",
        video_source="video",
        tracks=[
            Track(
                track_id=track_id,
                bbox=[0.0, 0.0, 100.0, 200.0],
                foot_point=[50.0, 200.0],
                confidence=0.9,
            )
        ],
    )


def test_cached_adaptive_cadence_holds_evidence_and_refreshes_on_interval():
    cadence = efc.CachedAdaptiveAuxiliaryCadence(
        interval_frames=3, iou_threshold=0.3
    )
    fall = [
        FallDetection(
            bbox=[0.0, 0.0, 100.0, 200.0],
            label="fall",
            confidence=0.9,
        )
    ]

    first, first_inferred = cadence.resolve(
        _tracking_result(0), fall, fall, use_auxiliary=True
    )
    held, held_inferred = cadence.resolve(
        _tracking_result(1), [], fall, use_auxiliary=True
    )
    refreshed, refreshed_inferred = cadence.resolve(
        _tracking_result(3), fall, fall, use_auxiliary=True
    )

    assert first is fall
    assert first_inferred is True
    assert [detection.label for detection in held] == ["fall"]
    assert held_inferred is False
    assert refreshed is fall
    assert refreshed_inferred is True


def test_runtime_and_cache_replay_match_across_fallback_hold_and_new_track():
    """Runtime과 cache replay가 복합 adaptive cadence에서도 같은 Event를 만든다."""

    class StubAuxiliaryModel:
        enabled = True

        def __init__(self, detections_by_call):
            self._detections_by_call = iter(detections_by_call)
            self.infer_calls = 0

        def infer(self, _frame):
            self.infer_calls += 1
            return next(self._detections_by_call)

    track_one = [0.0, 0.0, 100.0, 200.0]
    track_two = [120.0, 0.0, 220.0, 200.0]
    fall_one = FallDetection(bbox=track_one, label="fall", confidence=0.9)
    fall_both = [
        fall_one,
        FallDetection(bbox=track_two, label="fall", confidence=0.9),
    ]
    tracking_results = [
        _tracking_result(0),
        _tracking_result(1),
        _tracking_result(2),
        TrackingResult(
            frame_number=3,
            timestamp="00:00:00.300",
            video_source="video",
            tracks=[
                _tracking_result(3).tracks[0],
                Track(
                    track_id=2,
                    bbox=track_two,
                    foot_point=[170.0, 200.0],
                    confidence=0.9,
                ),
            ],
        ),
        TrackingResult(
            frame_number=4,
            timestamp="00:00:00.400",
            video_source="video",
            tracks=[
                _tracking_result(4).tracks[0],
                Track(
                    track_id=2,
                    bbox=track_two,
                    foot_point=[170.0, 200.0],
                    confidence=0.9,
                ),
            ],
        ),
    ]
    use_auxiliary = [False, True, True, True, True]
    raw_detections = [[], [fall_one], [fall_one], fall_both, fall_both]
    config = FallDetectorConfig(
        min_track_age_sec=0.1,
        model_candidate_entry_sec=0.05,
        model_confirm_sec=0.25,
        model_vote_window_sec=0.5,
    )

    runtime_model = StubAuxiliaryModel([[fall_one], fall_both])
    runtime_gate = MagicMock()
    runtime_gate.evaluate.side_effect = [
        SimpleNamespace(use_auxiliary=value) for value in use_auxiliary
    ]
    runtime_pipeline = FallPipeline(
        fps=10.0,
        detector_config=config,
        auxiliary_model=runtime_model,
        auxiliary_inference_interval_frames=3,
        pose_normal_gate=runtime_gate,
    )
    runtime_events = []
    runtime_diagnostics = []
    for tracking_result in tracking_results:
        runtime_events.extend(
            runtime_pipeline.process(
                np.zeros((8, 8, 3), dtype=np.uint8),
                tracking_result,
                diagnostics=runtime_diagnostics,
            )
        )

    replay_pipeline = FallPipeline(fps=10.0, detector_config=config)
    replay_cadence = efc.CachedAdaptiveAuxiliaryCadence(
        interval_frames=3, iou_threshold=0.3
    )
    replay_events = []
    replay_diagnostics = []
    replay_inference_frames = []
    for tracking_result, use_aux, raw in zip(
        tracking_results, use_auxiliary, raw_detections
    ):
        selected = raw if use_aux else efc._normal_detections(tracking_result)
        detections, inferred = replay_cadence.resolve(
            tracking_result, selected, raw, use_auxiliary=use_aux
        )
        if inferred:
            replay_inference_frames.append(tracking_result.frame_number)
        evidence = {
            item.track_id: item
            for item in match_detections_to_tracks(
                tracking_result.tracks, detections, iou_threshold=0.3
            )
        }
        replay_events.extend(
            replay_pipeline.process_with_evidence(
                tracking_result, evidence, diagnostics=replay_diagnostics
            )
        )

    assert runtime_model.infer_calls == 2
    assert replay_inference_frames == [1, 3]
    assert [event.frame_number for event in runtime_events] == [4]
    assert [event.frame_number for event in replay_events] == [4]
    assert runtime_diagnostics[0]["confirm_path"] == "model"
    assert replay_diagnostics[0]["confirm_path"] == "model"
