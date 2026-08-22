"""Phase 4 Tracker 3-way 비교 설정과 artifact provenance 검증."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Mapping, Sequence

import yaml

import phase4_recording_contract as recording_contract


SCHEMA_VERSION = "phase4_tracker_comparison_v1"
POLICY_VERSION = "phase4_tracker_comparison_policy_v1"
ARM_IDS = (
    "bytetrack_baseline",
    "botsort_without_reid",
    "botsort_with_reid",
)
_SHA256_LENGTH = 64


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_sha256(value: Mapping) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _is_sha256(value: object) -> bool:
    if not isinstance(value, str) or len(value) != _SHA256_LENGTH:
        return False
    return all(char in "0123456789abcdef" for char in value)


def _verify_file(
    *,
    path: Path,
    expected_sha256: str,
    label: str,
    required: bool,
) -> list[str]:
    if not path.is_file():
        return [f"{label} 파일이 없습니다: {path}"] if required else []
    actual = sha256_file(path)
    if actual != expected_sha256:
        return [f"{label} SHA-256 불일치: actual={actual}, expected={expected_sha256}"]
    return []


def _validate_arm(
    arm: Mapping,
    *,
    repo_root: Path,
    require_model_artifacts: bool,
) -> list[str]:
    errors: list[str] = []
    arm_id = arm.get("arm_id")
    config_path = repo_root / str(arm.get("tracker_config_path") or "")
    expected_config_sha = arm.get("tracker_config_sha256")
    if not _is_sha256(expected_config_sha):
        errors.append(f"{arm_id}: tracker_config_sha256이 올바르지 않습니다.")
        return errors
    errors.extend(
        _verify_file(
            path=config_path,
            expected_sha256=expected_config_sha,
            label=f"{arm_id} tracker config",
            required=True,
        )
    )
    if errors:
        return errors

    try:
        tracker_yaml = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        return [f"{arm_id}: tracker config를 읽을 수 없습니다: {exc}"]
    if not isinstance(tracker_yaml, dict):
        return [f"{arm_id}: tracker config root는 object여야 합니다."]

    expected_backend = arm.get("tracker_backend")
    if tracker_yaml.get("tracker_type") != expected_backend:
        errors.append(
            f"{arm_id}: tracker_type={tracker_yaml.get('tracker_type')!r}, "
            f"expected={expected_backend!r}"
        )
    with_reid = arm.get("with_reid")
    if not isinstance(with_reid, bool):
        errors.append(f"{arm_id}: with_reid는 boolean이어야 합니다.")
    if expected_backend == "botsort":
        if tracker_yaml.get("with_reid") is not with_reid:
            errors.append(
                f"{arm_id}: YAML with_reid={tracker_yaml.get('with_reid')!r}, "
                f"contract={with_reid!r}"
            )
    elif with_reid:
        errors.append(f"{arm_id}: ByteTrack arm에는 ReID를 켤 수 없습니다.")

    reid_path_value = arm.get("reid_model_path")
    reid_sha = arm.get("reid_model_sha256")
    if with_reid:
        if not isinstance(reid_path_value, str) or not reid_path_value:
            errors.append(f"{arm_id}: ReID ON arm에는 reid_model_path가 필요합니다.")
            return errors
        if reid_path_value == "auto" or reid_path_value.startswith(("http://", "https://")):
            errors.append(f"{arm_id}: ReID 모델 자동 다운로드와 URL 입력은 금지됩니다.")
        if tracker_yaml.get("model") != reid_path_value:
            errors.append(
                f"{arm_id}: YAML model={tracker_yaml.get('model')!r}, "
                f"contract={reid_path_value!r}"
            )
        if not _is_sha256(reid_sha):
            errors.append(f"{arm_id}: reid_model_sha256이 올바르지 않습니다.")
        else:
            errors.extend(
                _verify_file(
                    path=repo_root / reid_path_value,
                    expected_sha256=reid_sha,
                    label=f"{arm_id} ReID model",
                    required=require_model_artifacts,
                )
            )
    elif reid_path_value is not None or reid_sha is not None:
        errors.append(f"{arm_id}: ReID OFF arm에는 ReID model metadata를 둘 수 없습니다.")
    return errors


def validate_config(
    config: Mapping,
    *,
    repo_root: str | Path = ".",
    require_model_artifacts: bool = False,
) -> None:
    root = Path(repo_root).resolve()
    errors: list[str] = []
    if config.get("schema_version") != SCHEMA_VERSION:
        errors.append(
            f"schema_version={config.get('schema_version')!r}, expected={SCHEMA_VERSION!r}"
        )
    if config.get("policy_version") != POLICY_VERSION:
        errors.append(
            f"policy_version={config.get('policy_version')!r}, expected={POLICY_VERSION!r}"
        )
    ultralytics_version = config.get("ultralytics_version")
    if not isinstance(ultralytics_version, str) or not ultralytics_version.strip():
        errors.append("ultralytics_version은 비어 있지 않은 문자열이어야 합니다.")

    arms = config.get("arms")
    if not isinstance(arms, list):
        errors.append("arms는 배열이어야 합니다.")
        arms = []
    actual_arm_ids = tuple(arm.get("arm_id") for arm in arms if isinstance(arm, dict))
    if actual_arm_ids != ARM_IDS:
        errors.append(f"arm 순서/구성이 다릅니다: actual={actual_arm_ids}, expected={ARM_IDS}")
    for arm in arms:
        if not isinstance(arm, dict):
            errors.append("arm 항목은 object여야 합니다.")
            continue
        errors.extend(
            _validate_arm(
                arm,
                repo_root=root,
                require_model_artifacts=require_model_artifacts,
            )
        )

    selected_meta = config.get("selected_profile") or {}
    selected_path = root / str(selected_meta.get("path") or "")
    if not selected_path.is_file():
        errors.append(f"selected profile이 없습니다: {selected_path}")
    else:
        selected = json.loads(selected_path.read_text(encoding="utf-8"))
        actual_selected_sha = recording_contract.selected_execution_profile_sha256(
            selected
        )
        if actual_selected_sha != selected_meta.get("execution_profile_sha256"):
            errors.append(
                "selected execution profile SHA-256 불일치: "
                f"actual={actual_selected_sha}, "
                f"expected={selected_meta.get('execution_profile_sha256')}"
            )
        errors.extend(_validate_fixed_inference(config, selected))

    dataset = config.get("dataset") or {}
    for path_key, sha_key, label in (
        ("manifest_path", "manifest_sha256", "recordings manifest"),
        ("annotations_path", "annotations_sha256", "fall cause annotations"),
    ):
        expected_sha = dataset.get(sha_key)
        if not _is_sha256(expected_sha):
            errors.append(f"{label}의 {sha_key}가 올바르지 않습니다.")
            continue
        errors.extend(
            _verify_file(
                path=root / str(dataset.get(path_key) or ""),
                expected_sha256=expected_sha,
                label=label,
                required=True,
            )
        )

    fixed = config.get("fixed_inference") or {}
    for path_key, sha_key, label in (
        ("tracker_model_path", "tracker_model_sha256", "tracker model"),
        ("fall_model_path", "fall_model_sha256", "fall model"),
        ("fall_detector_config_path", "fall_detector_config_sha256", "fall config"),
    ):
        expected_sha = fixed.get(sha_key)
        if not _is_sha256(expected_sha):
            errors.append(f"{label}의 {sha_key}가 올바르지 않습니다.")
            continue
        required = require_model_artifacts or path_key == "fall_detector_config_path"
        errors.extend(
            _verify_file(
                path=root / str(fixed.get(path_key) or ""),
                expected_sha256=expected_sha,
                label=label,
                required=required,
            )
        )

    acceptance = config.get("acceptance") or {}
    if acceptance.get("cause_top1_denominator") != dataset.get(
        "cause_candidate_video_count"
    ):
        errors.append("Cause top-1 고정 분모가 dataset cohort와 다릅니다.")
    if errors:
        raise ValueError("Tracker 비교 계약 검증 실패:\n  - " + "\n  - ".join(errors))


def validate_ultralytics_version(config: Mapping, actual_version: str) -> None:
    expected_version = config.get("ultralytics_version")
    if actual_version != expected_version:
        raise ValueError(
            "Ultralytics 버전 불일치: "
            f"actual={actual_version!r}, expected={expected_version!r}"
        )


def _validate_fixed_inference(config: Mapping, selected: Mapping) -> list[str]:
    fixed = config.get("fixed_inference") or {}
    inference = selected.get("inference") or {}
    expected = {
        "tracker_type": inference.get("tracker"),
        "tracker_model_path": inference.get("tracker_model"),
        "tracker_model_sha256": inference.get("tracker_model_sha256"),
        "tracker_confidence": inference.get("tracker_confidence"),
        "fall_model_path": (selected.get("model") or {}).get("path"),
        "fall_model_sha256": (selected.get("model") or {}).get("sha256"),
        "fall_model_confidence": inference.get("fall_model_confidence"),
        "fall_detector_config_path": inference.get("fall_detector_config_path"),
        "fall_detector_config_sha256": inference.get("fall_detector_config_sha256"),
        "fall_model_iou_threshold": inference.get("fall_model_iou_threshold"),
        "fall_model_interval_frames": inference.get("fall_model_interval_frames"),
        "fall_pose_normal_gate_enabled": inference.get(
            "fall_pose_normal_gate_enabled"
        ),
        "evaluation_protocol_version": (selected.get("evaluation_protocol") or {}).get(
            "version"
        ),
    }
    return [
        f"fixed_inference.{key}={fixed.get(key)!r}, selected={value!r}"
        for key, value in expected.items()
        if fixed.get(key) != value
    ]


def validate_cohort(
    config: Mapping,
    manifest_rows: Sequence[Mapping[str, str]],
    annotation_rows: Sequence[Mapping[str, str]],
) -> None:
    dataset = config["dataset"]
    scenarios = set(dataset["multiperson_scenarios"])
    annotations = {row["video_id"]: row for row in annotation_rows}
    multiperson_ids = [
        row["video_id"]
        for row in manifest_rows
        if row["scenario_type"] in scenarios
        and row["primary_actor_id"] in {"A01", "A02"}
        and row["split_role"] == dataset["split"]
    ]
    candidate_count = sum(
        annotations[video_id]["cause_candidate_exists"] == "true"
        for video_id in multiperson_ids
    )
    cause_null_count = sum(
        row["split_role"] == dataset["split"]
        and row["label"] == "fall"
        and row["primary_actor_id"] in {"A01", "A02"}
        and annotations[row["video_id"]]["cause_candidate_exists"] == "false"
        for row in manifest_rows
    )
    actual = {
        "multiperson_video_count": len(multiperson_ids),
        "cause_candidate_video_count": candidate_count,
        "cause_null_video_count": cause_null_count,
    }
    errors = [
        f"{key}: actual={value}, expected={dataset[key]}"
        for key, value in actual.items()
        if value != dataset.get(key)
    ]
    if errors:
        raise ValueError("Tracker 비교 cohort 불일치:\n  - " + "\n  - ".join(errors))


def load_config(
    path: str | Path,
    *,
    repo_root: str | Path = ".",
    require_model_artifacts: bool = False,
) -> dict:
    config = json.loads(Path(path).read_text(encoding="utf-8"))
    validate_config(
        config,
        repo_root=repo_root,
        require_model_artifacts=require_model_artifacts,
    )
    return config


def arm_by_id(config: Mapping, arm_id: str) -> Mapping:
    for arm in config["arms"]:
        if arm["arm_id"] == arm_id:
            return arm
    raise ValueError(f"알 수 없는 arm_id입니다: {arm_id}")


def arm_provenance(arm: Mapping) -> dict:
    return {
        "arm_id": arm["arm_id"],
        "arm_config_sha256": canonical_sha256(arm),
        "tracker_config_path": arm["tracker_config_path"],
        "tracker_config_sha256": arm["tracker_config_sha256"],
        "tracker_backend": arm["tracker_backend"],
        "with_reid": arm["with_reid"],
        "reid_model_path": arm["reid_model_path"],
        "reid_model_sha256": arm["reid_model_sha256"],
    }


def validate_cache_arm(cache_manifest: Mapping, arm: Mapping) -> None:
    tracker = cache_manifest.get("tracker") or {}
    expected = {
        "tracker_config": arm["tracker_config_path"],
        "tracker_config_sha256": arm["tracker_config_sha256"],
        "tracker_backend": arm["tracker_backend"],
        "with_reid": arm["with_reid"],
        "reid_model_path": arm["reid_model_path"],
        "reid_model_sha256": arm["reid_model_sha256"],
    }
    errors = [
        f"tracker.{key}: cache={tracker.get(key)!r}, expected={value!r}"
        for key, value in expected.items()
        if tracker.get(key) != value
    ]
    if errors:
        raise ValueError("Tracker arm cache provenance 불일치:\n  - " + "\n  - ".join(errors))
