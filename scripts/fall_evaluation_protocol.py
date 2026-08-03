"""Phase 4 공식 낙상 평가 protocol과 provenance 공통 helpers."""

from __future__ import annotations

import csv
import hashlib
import math
import re
import subprocess
from pathlib import Path
from typing import Optional


CONTRACT_VERSION = "phase4_contract_v1"
EVALUATION_PROTOCOL_VERSION = "phase4_fall_eval_v1"
CAUCAFALL_ANNOTATION_VERSION = "caucafall_annotation_v2"

EARLY_TOLERANCE_SEC = 0.2
TIMELY_WINDOW_SEC = 2.0

EVENT_MATCHING_RULE = "first_fall_suspect_in_closed_timely_window_v1"
DUPLICATE_RULE = "second_fall_suspect_from_window_start_to_video_end_v1"
FAR_DENOMINATOR_RULE = "processed_no_fall_frames_over_fps_v1"

_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_REPO_ROOT = Path(__file__).resolve().parent.parent
_CAUCAFALL_V2_REQUIRED_COLUMNS = {
    "video_id",
    "label",
    "video_path",
    "dataset_fall_label_frame",
    "fall_start_frame",
    "impact_frame",
    "lying_start_frame",
    "review_status",
}
_CAUCAFALL_FRAME_COLUMNS = (
    "dataset_fall_label_frame",
    "fall_start_frame",
    "impact_frame",
    "lying_start_frame",
)
_VALID_LABELS = {"fall", "no_fall"}
_VALID_REVIEW_STATUSES = {"pending", "reviewed", "needs_review"}


def add_cli_argument(parser) -> None:
    """공식 protocol을 명시적으로 선택하는 공통 CLI option을 추가한다."""
    parser.add_argument(
        "--evaluation-protocol-version",
        choices=[EVALUATION_PROTOCOL_VERSION],
        default=None,
        help=(
            "공식 Phase 4 평가 protocol. 지정하면 annotation V2, reviewed-only, "
            "early tolerance 0.2초와 timely window 2.0초를 강제하고 provenance를 기록한다."
        ),
    )


def sha256_file(path: str | Path) -> Optional[str]:
    target = Path(path)
    if not target.is_file():
        return None
    digest = hashlib.sha256()
    with target.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_caucafall_v2_annotations(path: str | Path) -> str:
    """공식 CAUCAFall V2 CSV 전체를 filtering 전에 fail-closed 검증한다."""
    with Path(path).open(encoding="utf-8", newline="") as file:
        reader = csv.DictReader(file)
        fieldnames = set(reader.fieldnames or [])
        missing_columns = _CAUCAFALL_V2_REQUIRED_COLUMNS - fieldnames
        if missing_columns:
            raise ValueError(
                f"{CAUCAFALL_ANNOTATION_VERSION} 필수 컬럼이 없습니다: "
                f"{sorted(missing_columns)}"
            )
        raw_rows = list(reader)

    if not raw_rows:
        raise ValueError(f"{CAUCAFALL_ANNOTATION_VERSION} CSV에 annotation 행이 없습니다.")

    errors = []
    seen_ids = {}
    for row_number, raw in enumerate(raw_rows, start=2):
        video_id = (raw.get("video_id") or "").strip()
        label = (raw.get("label") or "").strip()
        video_path = (raw.get("video_path") or "").strip()
        review_status = (raw.get("review_status") or "").strip()
        row_name = video_id or f"row {row_number}"

        if not video_id:
            errors.append(f"row {row_number}: video_id가 비어 있습니다.")
        else:
            seen_ids[video_id] = seen_ids.get(video_id, 0) + 1
        if label not in _VALID_LABELS:
            errors.append(
                f"{row_name}: label='{label}'은(는) {sorted(_VALID_LABELS)} 중 하나여야 합니다."
            )
        if not video_path:
            errors.append(f"{row_name}: video_path가 비어 있습니다.")
        if review_status not in _VALID_REVIEW_STATUSES:
            errors.append(
                f"{row_name}: review_status='{review_status}'는 "
                f"{sorted(_VALID_REVIEW_STATUSES)} 중 하나여야 합니다."
            )

        frame_values = {}
        for column in _CAUCAFALL_FRAME_COLUMNS:
            value = (raw.get(column) or "").strip()
            if not value:
                frame_values[column] = None
                continue
            try:
                parsed = int(value)
            except ValueError:
                errors.append(f"{row_name}: {column}='{value}'는 정수여야 합니다.")
                frame_values[column] = None
                continue
            if parsed < 0:
                errors.append(f"{row_name}: {column}={parsed}는 0 이상이어야 합니다.")
            frame_values[column] = parsed

        if label == "fall" and review_status == "reviewed":
            missing_frames = [
                column
                for column in _CAUCAFALL_FRAME_COLUMNS
                if frame_values[column] is None
            ]
            if missing_frames:
                errors.append(
                    f"{row_name}: reviewed V2 fall 행은 {missing_frames}이(가) 필수입니다."
                )

        if label == "fall":
            ordered_frames = [
                (column, frame_values[column])
                for column in (
                    "fall_start_frame",
                    "impact_frame",
                    "lying_start_frame",
                )
                if frame_values[column] is not None
            ]
            for (name_a, value_a), (name_b, value_b) in zip(
                ordered_frames, ordered_frames[1:]
            ):
                if value_a <= value_b:
                    continue
                errors.append(
                    f"{row_name}: {name_a}({value_a}) <= {name_b}({value_b})여야 합니다."
                )

    duplicates = sorted(video_id for video_id, count in seen_ids.items() if count > 1)
    if duplicates:
        errors.append(f"중복된 video_id: {duplicates}")
    if errors:
        raise ValueError(
            "공식 annotation 검증 실패 ("
            + str(len(errors))
            + "건):\n  - "
            + "\n  - ".join(errors)
        )
    return CAUCAFALL_ANNOTATION_VERSION


def validate_protocol_request(
    protocol_version: Optional[str],
    annotations_path: str | Path,
    early_tolerance_sec: float,
    timely_window_sec: float,
    include_unreviewed: bool,
) -> Optional[str]:
    """공식 protocol 요청을 검증하고 annotation schema version을 반환한다."""
    if protocol_version is None:
        return None
    if protocol_version != EVALUATION_PROTOCOL_VERSION:
        raise ValueError(f"지원하지 않는 평가 protocol입니다: {protocol_version}")
    if not math.isclose(
        early_tolerance_sec,
        EARLY_TOLERANCE_SEC,
        rel_tol=0.0,
        abs_tol=1e-12,
    ):
        raise ValueError(
            f"{protocol_version}의 early_tolerance_sec는 "
            f"{EARLY_TOLERANCE_SEC}로 고정입니다: {early_tolerance_sec}"
        )
    if not math.isclose(
        timely_window_sec,
        TIMELY_WINDOW_SEC,
        rel_tol=0.0,
        abs_tol=1e-12,
    ):
        raise ValueError(
            f"{protocol_version}의 timely_window_sec는 "
            f"{TIMELY_WINDOW_SEC}로 고정입니다: {timely_window_sec}"
        )
    if include_unreviewed:
        raise ValueError(f"{protocol_version} 공식 평가는 reviewed annotation만 허용합니다.")

    return validate_caucafall_v2_annotations(annotations_path)


def validate_official_cache_manifest(manifest: dict) -> None:
    """공식 cache replay에 필요한 signal 생성 provenance를 검증한다."""
    tracker = manifest.get("tracker") or {}
    auxiliary = manifest.get("auxiliary_model") or {}
    missing = []
    if not _SHA256_PATTERN.fullmatch(str(tracker.get("model_sha256") or "")):
        missing.append("tracker.model_sha256")
    if not _is_resolved_device(tracker.get("resolved_device")):
        missing.append("tracker.resolved_device")
    if not _is_resolved_device(auxiliary.get("resolved_device")):
        missing.append("auxiliary_model.resolved_device")
    if not _SHA256_PATTERN.fullmatch(str(auxiliary.get("model_sha256") or "")):
        missing.append("auxiliary_model.model_sha256")
    if missing:
        raise ValueError(
            "공식 Phase 4 평가에 필요한 cache provenance가 없습니다: "
            + ", ".join(missing)
            + ". scripts/cache_fall_signals.py로 새 cache를 생성하세요."
        )


def _is_resolved_device(value) -> bool:
    if not isinstance(value, str):
        return False
    normalized = value.strip().lower()
    return bool(normalized) and normalized != "auto"


def normalize_resolved_device(value, component_name: str) -> str:
    """실제 inference device를 검증하고 manifest용 문자열로 정규화한다."""
    if not _is_resolved_device(value):
        raise ValueError(
            f"{component_name}의 실제 inference device를 확인할 수 없습니다: "
            f"{value!r}"
        )
    return value.strip()


def _git_state(repo_root: Path = _REPO_ROOT) -> tuple[str, bool]:
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValueError("evaluator Git revision을 확인할 수 없습니다.") from exc
    return commit, bool(status.strip())


def build_metadata(
    *,
    annotation_schema_version: str,
    model_sha256: Optional[str],
    config_path: str | Path,
    tracker: str,
    tracker_config: dict,
    device: dict,
    evaluator_git_commit: Optional[str] = None,
    evaluator_git_dirty: Optional[bool] = None,
) -> dict:
    """공식 결과 JSON root에 넣을 재현 metadata를 만든다."""
    if annotation_schema_version != CAUCAFALL_ANNOTATION_VERSION:
        raise ValueError(f"공식 CAUCAFall annotation schema가 아닙니다: {annotation_schema_version}")
    if not _SHA256_PATTERN.fullmatch(str(model_sha256 or "")):
        raise ValueError("공식 평가에는 보조 낙상 모델 SHA-256이 필요합니다.")
    if not tracker or not isinstance(tracker_config, dict):
        raise ValueError("공식 평가에는 tracker와 tracker_config가 필요합니다.")
    if not _SHA256_PATTERN.fullmatch(str(tracker_config.get("model_sha256") or "")):
        raise ValueError("공식 평가에는 tracker 모델 SHA-256이 필요합니다.")
    config_sha256 = sha256_file(config_path)
    if not _SHA256_PATTERN.fullmatch(str(config_sha256 or "")):
        raise ValueError(f"공식 평가 config를 읽을 수 없습니다: {config_path}")

    if evaluator_git_commit is None or evaluator_git_dirty is None:
        detected_commit, detected_dirty = _git_state()
        evaluator_git_commit = evaluator_git_commit or detected_commit
        evaluator_git_dirty = (
            detected_dirty if evaluator_git_dirty is None else evaluator_git_dirty
        )
    if not re.fullmatch(r"[0-9a-f]{40}", str(evaluator_git_commit or "")):
        raise ValueError("공식 평가에는 40자리 evaluator Git commit이 필요합니다.")
    if not isinstance(device, dict):
        raise ValueError("공식 평가에는 device metadata object가 필요합니다.")
    tracker_device = device.get("tracker")
    auxiliary_device = device.get("auxiliary_model")
    if not _is_resolved_device(tracker_device):
        raise ValueError("공식 평가에는 실제 tracker inference device가 필요합니다.")
    if not _is_resolved_device(auxiliary_device):
        raise ValueError("공식 평가에는 실제 보조 모델 inference device가 필요합니다.")
    device = {
        **device,
        "tracker": tracker_device.strip(),
        "auxiliary_model": auxiliary_device.strip(),
    }

    return {
        "contract_version": CONTRACT_VERSION,
        "evaluation_protocol_version": EVALUATION_PROTOCOL_VERSION,
        "annotation_schema_version": annotation_schema_version,
        "evaluator_git_commit": evaluator_git_commit,
        "evaluator_git_dirty": evaluator_git_dirty,
        "model_sha256": model_sha256,
        "config_sha256": config_sha256,
        "tracker": tracker,
        "tracker_config": tracker_config,
        "device": device,
        "early_tolerance_sec": EARLY_TOLERANCE_SEC,
        "timely_window_sec": TIMELY_WINDOW_SEC,
        "event_matching_rule": EVENT_MATCHING_RULE,
        "duplicate_rule": DUPLICATE_RULE,
        "far_denominator_rule": FAR_DENOMINATOR_RULE,
    }
