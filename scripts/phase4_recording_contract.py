"""Phase 4 직접 촬영 manifest와 낙상·Cause annotation 계약 helpers."""

from __future__ import annotations

import csv
import hashlib
import math
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable, Mapping, Optional, Sequence


RECORDINGS_MANIFEST_SCHEMA_VERSION = "phase4_recordings_manifest_v1"
FALL_CAUSE_ANNOTATION_SCHEMA_VERSION = "phase4_fall_cause_v1"
ZONE_INTERVALS_SCHEMA_VERSION = "phase4_zone_intervals_v1"
SCENARIO_SEEDED_DRAFT_NOTE = "scenario-seeded draft; frame review required"

MANIFEST_FIELDS = (
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
)

FALL_CAUSE_FIELDS = (
    "video_id",
    "label",
    "fall_start_frame",
    "impact_frame",
    "lying_start_frame",
    "recovery_frame",
    "victim_actor_id",
    "contact_occurred",
    "cause_candidate_exists",
    "cause_actor_id",
    "contact_frame",
    "review_status",
    "reviewer_id",
    "second_reviewer_id",
    "notes",
)

ZONE_INTERVAL_FIELDS = (
    "video_id",
    "zone_id",
    "interval_index",
    "enter_frame",
    "exit_frame",
    "dwell_start_frame",
    "review_status",
    "notes",
)

VALID_LABELS = {"fall", "no_fall"}
VALID_SPLIT_ROLES = {
    "train",
    "internal_validation",
    "diagnostic",
    "test",
    "external_evaluation",
}
VALID_REVIEW_STATUSES = {"pending", "needs_review", "reviewed"}
VALID_CONSENT_STATUSES = {"confirmed", "excluded"}

_VIDEO_ID_PATTERN = re.compile(
    r"^P4_(?P<session_id>S\d{2})_(?P<primary_actor_id>A\d{2})_"
    r"(?P<scenario_type>[a-z0-9]+(?:_[a-z0-9]+)*)_"
    r"(?P<take>\d{2})_(?P<camera_id>cam\d{2})$"
)
_ACTOR_ID_PATTERN = re.compile(r"^A\d{2}$")
_SCENARIO_PATTERN = re.compile(r"^[a-z0-9]+(?:_[a-z0-9]+)*$")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class RecordingName:
    video_id: str
    session_id: str
    primary_actor_id: str
    scenario_type: str
    take: str
    camera_id: str


def parse_recording_name(value: str) -> RecordingName:
    """계약 파일명 또는 확장자 없는 video_id를 구조화한다."""
    name = Path(value).name
    video_id = name[:-4] if name.lower().endswith(".mp4") else name
    match = _VIDEO_ID_PATTERN.fullmatch(video_id)
    if match is None:
        raise ValueError(
            f"촬영 파일명이 계약과 다릅니다: {value!r} "
            "(예: P4_S01_A01_fall_backward_01_cam01.mp4)"
        )
    return RecordingName(video_id=video_id, **match.groupdict())


def split_actor_ids(value: str) -> tuple[str, ...]:
    actors = tuple(part.strip() for part in value.split("|") if part.strip())
    if not actors:
        raise ValueError("actor_ids가 비어 있습니다.")
    if len(set(actors)) != len(actors):
        raise ValueError(f"actor_ids에 중복이 있습니다: {value!r}")
    invalid = [actor for actor in actors if _ACTOR_ID_PATTERN.fullmatch(actor) is None]
    if invalid:
        raise ValueError(f"잘못된 actor ID입니다: {invalid}")
    return actors


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_csv_rows(path: str | Path, expected_fields: Sequence[str]) -> list[dict[str, str]]:
    target = Path(path)
    with target.open(encoding="utf-8", newline="") as file:
        reader = csv.DictReader(file)
        actual_fields = tuple(reader.fieldnames or ())
        if actual_fields != tuple(expected_fields):
            raise ValueError(
                f"{target}: CSV header가 계약과 다릅니다. "
                f"expected={list(expected_fields)}, actual={list(actual_fields)}"
            )
        rows = [dict(row) for row in reader]
    if not rows:
        raise ValueError(f"{target}: CSV에 행이 없습니다.")
    return rows


def write_csv_atomic(
    path: str | Path,
    fields: Sequence[str],
    rows: Iterable[Mapping[str, object]],
    *,
    force: bool = False,
) -> None:
    """CSV를 같은 디렉터리의 임시 파일에 쓴 뒤 원자적으로 교체한다."""
    target = Path(path)
    if target.exists() and not force:
        raise FileExistsError(f"이미 파일이 있습니다: {target} (--force 필요)")
    target.parent.mkdir(parents=True, exist_ok=True)

    temp_path: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            prefix=f".{target.name}.",
            suffix=".tmp",
            dir=target.parent,
            delete=False,
        ) as file:
            temp_path = Path(file.name)
            writer = csv.DictWriter(
                file,
                fieldnames=list(fields),
                extrasaction="raise",
                lineterminator="\n",
            )
            writer.writeheader()
            writer.writerows(rows)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temp_path, target)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()


def _parse_positive_float(value: str, field: str, row_name: str, errors: list[str]) -> None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        errors.append(f"{row_name}: {field}={value!r}는 숫자여야 합니다.")
        return
    if not math.isfinite(parsed) or parsed <= 0:
        errors.append(f"{row_name}: {field}={value!r}는 finite 양수여야 합니다.")


def _parse_positive_int(value: str, field: str, row_name: str, errors: list[str]) -> None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        errors.append(f"{row_name}: {field}={value!r}는 정수여야 합니다.")
        return
    if parsed <= 0:
        errors.append(f"{row_name}: {field}={value!r}는 양수여야 합니다.")


def _raise_errors(schema_name: str, errors: list[str]) -> None:
    if errors:
        raise ValueError(
            f"{schema_name} 검증 실패 ({len(errors)}건):\n  - "
            + "\n  - ".join(errors)
        )


def validate_recordings_manifest(
    rows: Sequence[Mapping[str, str]],
    *,
    repo_root: str | Path | None = None,
    verify_files: bool = False,
    verify_checksums: bool = False,
) -> None:
    """manifest 구조와 선택적으로 로컬 파일·checksum을 fail-closed 검증한다."""
    if not rows:
        raise ValueError(f"{RECORDINGS_MANIFEST_SCHEMA_VERSION}: 행이 없습니다.")
    if verify_checksums and not verify_files:
        raise ValueError("verify_checksums=True이면 verify_files=True도 필요합니다.")

    root = Path(repo_root).resolve() if repo_root is not None else None
    if verify_files and root is None:
        raise ValueError("파일 검증에는 repo_root가 필요합니다.")

    errors: list[str] = []
    seen_video_ids: set[str] = set()
    seen_paths: set[str] = set()
    seen_checksums: dict[str, str] = {}

    for row_number, row in enumerate(rows, start=2):
        video_id = (row.get("video_id") or "").strip()
        row_name = video_id or f"row {row_number}"
        if video_id in seen_video_ids:
            errors.append(f"{row_name}: 중복 video_id입니다.")
        seen_video_ids.add(video_id)

        try:
            parsed_name = parse_recording_name(video_id)
        except ValueError as exc:
            errors.append(str(exc))
            parsed_name = None

        actors: tuple[str, ...] = ()
        try:
            actors = split_actor_ids((row.get("actor_ids") or "").strip())
        except ValueError as exc:
            errors.append(f"{row_name}: {exc}")

        primary_actor = (row.get("primary_actor_id") or "").strip()
        if actors and primary_actor not in actors:
            errors.append(f"{row_name}: primary_actor_id가 actor_ids에 없습니다.")

        if parsed_name is not None:
            expected = {
                "session_id": parsed_name.session_id,
                "primary_actor_id": parsed_name.primary_actor_id,
                "scenario_type": parsed_name.scenario_type,
                "camera_id": parsed_name.camera_id,
            }
            for field, expected_value in expected.items():
                actual_value = (row.get(field) or "").strip()
                if actual_value != expected_value:
                    errors.append(
                        f"{row_name}: {field}={actual_value!r}, "
                        f"파일명 기준값은 {expected_value!r}입니다."
                    )

        scenario = (row.get("scenario_type") or "").strip()
        if _SCENARIO_PATTERN.fullmatch(scenario) is None:
            errors.append(f"{row_name}: scenario_type이 lowercase snake_case가 아닙니다.")
        if (row.get("label") or "").strip() not in VALID_LABELS:
            errors.append(f"{row_name}: label은 {sorted(VALID_LABELS)} 중 하나여야 합니다.")
        if (row.get("split_role") or "").strip() not in VALID_SPLIT_ROLES:
            errors.append(
                f"{row_name}: split_role은 {sorted(VALID_SPLIT_ROLES)} 중 하나여야 합니다."
            )
        if (row.get("review_status") or "").strip() not in VALID_REVIEW_STATUSES:
            errors.append(
                f"{row_name}: review_status는 {sorted(VALID_REVIEW_STATUSES)} 중 하나여야 합니다."
            )
        if (row.get("consent_status") or "").strip() not in VALID_CONSENT_STATUSES:
            errors.append(
                f"{row_name}: consent_status는 {sorted(VALID_CONSENT_STATUSES)} 중 하나여야 합니다."
            )

        _parse_positive_float(row.get("fps") or "", "fps", row_name, errors)
        for field in ("frame_count", "width", "height"):
            _parse_positive_int(row.get(field) or "", field, row_name, errors)

        checksum = (row.get("checksum_sha256") or "").strip()
        if _SHA256_PATTERN.fullmatch(checksum) is None:
            errors.append(f"{row_name}: checksum_sha256 형식이 잘못됐습니다.")
        elif checksum in seen_checksums:
            errors.append(
                f"{row_name}: {seen_checksums[checksum]}와 동일한 영상 checksum입니다."
            )
        else:
            seen_checksums[checksum] = row_name

        video_path_text = (row.get("video_path") or "").strip()
        posix_path = PurePosixPath(video_path_text)
        if (
            not video_path_text
            or posix_path.is_absolute()
            or "\\" in video_path_text
            or ".." in posix_path.parts
        ):
            errors.append(f"{row_name}: video_path는 안전한 프로젝트 상대 POSIX 경로여야 합니다.")
        elif posix_path.name != f"{video_id}.mp4":
            errors.append(f"{row_name}: video_path 파일명이 video_id와 일치하지 않습니다.")
        elif video_path_text in seen_paths:
            errors.append(f"{row_name}: 중복 video_path입니다.")
        else:
            seen_paths.add(video_path_text)

        if verify_files and root is not None and video_path_text:
            candidate = root / video_path_text
            try:
                resolved = candidate.resolve(strict=True)
                resolved.relative_to(root)
            except (FileNotFoundError, ValueError):
                errors.append(f"{row_name}: video_path가 없거나 저장소 밖을 가리킵니다.")
                continue
            if not resolved.is_file():
                errors.append(f"{row_name}: video_path가 파일이 아닙니다.")
            elif verify_checksums and _SHA256_PATTERN.fullmatch(checksum):
                actual_checksum = sha256_file(resolved)
                if actual_checksum != checksum:
                    errors.append(f"{row_name}: 실제 파일 SHA-256이 manifest와 다릅니다.")

    _raise_errors(RECORDINGS_MANIFEST_SCHEMA_VERSION, errors)


def load_recordings_manifest(
    path: str | Path,
    *,
    repo_root: str | Path | None = None,
    verify_files: bool = False,
    verify_checksums: bool = False,
) -> list[dict[str, str]]:
    rows = load_csv_rows(path, MANIFEST_FIELDS)
    validate_recordings_manifest(
        rows,
        repo_root=repo_root,
        verify_files=verify_files,
        verify_checksums=verify_checksums,
    )
    return rows


def _optional_frame(
    value: str,
    field: str,
    row_name: str,
    frame_count: int,
    errors: list[str],
) -> Optional[int]:
    text = (value or "").strip()
    if not text:
        return None
    try:
        frame = int(text)
    except ValueError:
        errors.append(f"{row_name}: {field}={text!r}는 정수여야 합니다.")
        return None
    if frame < 0 or frame >= frame_count:
        errors.append(
            f"{row_name}: {field}={frame}은 frame 범위 [0, {frame_count}) 밖입니다."
        )
    return frame


def validate_fall_cause_annotations(
    rows: Sequence[Mapping[str, str]],
    manifest_rows: Sequence[Mapping[str, str]],
    *,
    require_reviewed: bool = False,
) -> None:
    """직접 촬영 annotation의 frame·actor·Cause 관계를 검증한다."""
    manifest_by_video = {row["video_id"]: row for row in manifest_rows}
    if len(manifest_by_video) != len(manifest_rows):
        raise ValueError("manifest에 중복 video_id가 있습니다.")
    if not rows:
        raise ValueError(f"{FALL_CAUSE_ANNOTATION_SCHEMA_VERSION}: 행이 없습니다.")

    errors: list[str] = []
    seen_video_ids: set[str] = set()
    for row_number, row in enumerate(rows, start=2):
        video_id = (row.get("video_id") or "").strip()
        row_name = video_id or f"row {row_number}"
        if video_id in seen_video_ids:
            errors.append(f"{row_name}: 중복 video_id입니다.")
        seen_video_ids.add(video_id)

        manifest = manifest_by_video.get(video_id)
        if manifest is None:
            errors.append(f"{row_name}: manifest에 없는 video_id입니다.")
            continue
        frame_count = int(manifest["frame_count"])
        actors = set(split_actor_ids(manifest["actor_ids"]))
        label = (row.get("label") or "").strip()
        if label != manifest["label"]:
            errors.append(f"{row_name}: annotation과 manifest label이 다릅니다.")

        review_status = (row.get("review_status") or "").strip()
        if review_status not in VALID_REVIEW_STATUSES:
            errors.append(
                f"{row_name}: review_status는 {sorted(VALID_REVIEW_STATUSES)} 중 하나여야 합니다."
            )
        if require_reviewed and review_status != "reviewed":
            errors.append(f"{row_name}: 공식 평가 전 review_status=reviewed가 필요합니다.")

        frames = {
            field: _optional_frame(row.get(field) or "", field, row_name, frame_count, errors)
            for field in (
                "fall_start_frame",
                "impact_frame",
                "lying_start_frame",
                "recovery_frame",
                "contact_frame",
            )
        }

        fall_order = [
            (field, frames[field])
            for field in (
                "fall_start_frame",
                "impact_frame",
                "lying_start_frame",
                "recovery_frame",
            )
            if frames[field] is not None
        ]
        for (left_name, left), (right_name, right) in zip(fall_order, fall_order[1:]):
            if left is not None and right is not None and left > right:
                errors.append(
                    f"{row_name}: {left_name}({left}) <= {right_name}({right})여야 합니다."
                )

        victim_actor = (row.get("victim_actor_id") or "").strip()
        if victim_actor and victim_actor not in actors:
            errors.append(f"{row_name}: victim_actor_id가 manifest actor_ids에 없습니다.")

        if label == "fall":
            if review_status == "reviewed":
                required_frames = (
                    "fall_start_frame",
                    "impact_frame",
                    "lying_start_frame",
                )
                missing = [field for field in required_frames if frames[field] is None]
                if missing:
                    errors.append(f"{row_name}: reviewed fall의 필수 frame 누락: {missing}")
                if not victim_actor:
                    errors.append(f"{row_name}: reviewed fall은 victim_actor_id가 필요합니다.")
        elif label == "no_fall":
            populated = [field for field, value in fall_order if value is not None]
            if populated:
                errors.append(f"{row_name}: no_fall 행에는 낙상 frame을 입력할 수 없습니다.")
        else:
            errors.append(f"{row_name}: label은 {sorted(VALID_LABELS)} 중 하나여야 합니다.")

        contact = (row.get("contact_occurred") or "").strip()
        cause_exists = (row.get("cause_candidate_exists") or "").strip()
        for field, value in (
            ("contact_occurred", contact),
            ("cause_candidate_exists", cause_exists),
        ):
            if value not in {"", "true", "false"}:
                errors.append(f"{row_name}: {field}는 true, false 또는 빈 값이어야 합니다.")
            if review_status == "reviewed" and value not in {"true", "false"}:
                errors.append(f"{row_name}: reviewed 행의 {field}는 필수입니다.")

        if contact != "true" and frames["contact_frame"] is not None:
            errors.append(f"{row_name}: contact_frame은 contact_occurred=true일 때만 허용됩니다.")
        if review_status == "reviewed" and contact == "true" and frames["contact_frame"] is None:
            errors.append(f"{row_name}: contact_occurred=true이면 contact_frame이 필요합니다.")

        cause_actor = (row.get("cause_actor_id") or "").strip()
        if cause_actor and cause_actor not in actors:
            errors.append(f"{row_name}: cause_actor_id가 manifest actor_ids에 없습니다.")
        if cause_actor and cause_actor == victim_actor:
            errors.append(f"{row_name}: cause actor와 victim actor는 달라야 합니다.")
        if cause_exists != "true" and cause_actor:
            errors.append(
                f"{row_name}: cause_actor_id는 cause_candidate_exists=true일 때만 허용됩니다."
            )
        if review_status == "reviewed" and cause_exists == "true" and not cause_actor:
            errors.append(f"{row_name}: cause_candidate_exists=true이면 cause_actor_id가 필요합니다.")

        reviewer = (row.get("reviewer_id") or "").strip()
        second_reviewer = (row.get("second_reviewer_id") or "").strip()
        if reviewer and second_reviewer and reviewer == second_reviewer:
            errors.append(f"{row_name}: 두 reviewer ID는 서로 달라야 합니다.")
        if review_status == "reviewed" and (not reviewer or not second_reviewer):
            errors.append(f"{row_name}: reviewed 행은 서로 다른 reviewer 2명이 필요합니다.")

    missing_annotations = sorted(set(manifest_by_video) - seen_video_ids)
    if missing_annotations:
        errors.append(f"manifest 영상의 annotation이 누락됐습니다: {missing_annotations}")
    unknown_annotations = sorted(seen_video_ids - set(manifest_by_video))
    if unknown_annotations:
        errors.append(f"manifest에 없는 annotation이 있습니다: {unknown_annotations}")

    _raise_errors(FALL_CAUSE_ANNOTATION_SCHEMA_VERSION, errors)


def load_fall_cause_annotations(
    path: str | Path,
    manifest_rows: Sequence[Mapping[str, str]],
    *,
    require_reviewed: bool = False,
) -> list[dict[str, str]]:
    rows = load_csv_rows(path, FALL_CAUSE_FIELDS)
    validate_fall_cause_annotations(rows, manifest_rows, require_reviewed=require_reviewed)
    return rows


def validate_zone_intervals(
    rows: Sequence[Mapping[str, str]],
    manifest_rows: Sequence[Mapping[str, str]],
    *,
    require_reviewed: bool = False,
) -> None:
    """Zone 진입·이탈 interval의 frame·순서·중복을 manifest 기준으로 검증한다."""
    manifest_by_video = {row["video_id"]: row for row in manifest_rows}
    if len(manifest_by_video) != len(manifest_rows):
        raise ValueError("manifest에 중복 video_id가 있습니다.")
    if not rows:
        raise ValueError(f"{ZONE_INTERVALS_SCHEMA_VERSION}: 행이 없습니다.")

    errors: list[str] = []
    seen_keys: set[tuple[str, str, int]] = set()
    indexes_by_video_zone: dict[tuple[str, str], list[int]] = {}
    seen_video_ids: set[str] = set()
    for row_number, row in enumerate(rows, start=2):
        video_id = (row.get("video_id") or "").strip()
        zone_id = (row.get("zone_id") or "").strip()
        interval_index_text = (row.get("interval_index") or "").strip()
        row_name = f"{video_id or f'row {row_number}'}/{zone_id}/{interval_index_text}"
        seen_video_ids.add(video_id)

        manifest = manifest_by_video.get(video_id)
        if manifest is None:
            errors.append(f"{row_name}: manifest에 없는 video_id입니다.")
            continue
        frame_count = int(manifest["frame_count"])

        if not zone_id:
            errors.append(f"{row_name}: zone_id가 비어 있습니다.")

        interval_index: Optional[int] = None
        try:
            interval_index = int(interval_index_text)
            if interval_index < 1:
                raise ValueError
        except ValueError:
            errors.append(f"{row_name}: interval_index는 1 이상의 정수여야 합니다.")

        if interval_index is not None:
            key = (video_id, zone_id, interval_index)
            if key in seen_keys:
                errors.append(f"{row_name}: 중복 (video_id, zone_id, interval_index)입니다.")
            seen_keys.add(key)
            indexes_by_video_zone.setdefault((video_id, zone_id), []).append(interval_index)

        review_status = (row.get("review_status") or "").strip()
        if review_status not in VALID_REVIEW_STATUSES:
            errors.append(
                f"{row_name}: review_status는 {sorted(VALID_REVIEW_STATUSES)} 중 하나여야 합니다."
            )
        elif require_reviewed and review_status != "reviewed":
            errors.append(f"{row_name}: 공식 측정 전 review_status=reviewed가 필요합니다.")

        enter_frame = _optional_frame(
            row.get("enter_frame") or "", "enter_frame", row_name, frame_count, errors
        )
        exit_frame = _optional_frame(
            row.get("exit_frame") or "", "exit_frame", row_name, frame_count, errors
        )
        dwell_frame = _optional_frame(
            row.get("dwell_start_frame") or "",
            "dwell_start_frame",
            row_name,
            frame_count,
            errors,
        )

        if review_status == "reviewed" and (enter_frame is None or exit_frame is None):
            errors.append(f"{row_name}: reviewed 행은 enter_frame·exit_frame이 필요합니다.")
        if enter_frame is not None and exit_frame is not None and enter_frame >= exit_frame:
            errors.append(
                f"{row_name}: enter_frame({enter_frame}) < exit_frame({exit_frame})이어야 합니다."
            )
        if dwell_frame is not None:
            if enter_frame is None or exit_frame is None:
                errors.append(
                    f"{row_name}: dwell_start_frame은 enter_frame·exit_frame이 있어야 합니다."
                )
            elif not (enter_frame <= dwell_frame < exit_frame):
                errors.append(
                    f"{row_name}: dwell_start_frame({dwell_frame})은 "
                    f"[{enter_frame}, {exit_frame}) 안에 있어야 합니다."
                )

    for (video_id, zone_id), indexes in sorted(indexes_by_video_zone.items()):
        expected = list(range(1, len(indexes) + 1))
        if sorted(indexes) != expected:
            errors.append(
                f"{video_id}/{zone_id}: interval_index는 1부터 연속이어야 합니다 "
                f"(actual={sorted(indexes)}, expected={expected})."
            )

    missing = sorted(set(manifest_by_video) - seen_video_ids)
    if missing:
        errors.append(f"manifest 영상의 zone interval이 누락됐습니다: {missing}")
    unknown = sorted(seen_video_ids - set(manifest_by_video))
    if unknown:
        errors.append(f"manifest에 없는 zone interval이 있습니다: {unknown}")

    _raise_errors(ZONE_INTERVALS_SCHEMA_VERSION, errors)


def load_zone_intervals(
    path: str | Path,
    manifest_rows: Sequence[Mapping[str, str]],
    *,
    require_reviewed: bool = False,
) -> list[dict[str, str]]:
    rows = load_csv_rows(path, ZONE_INTERVAL_FIELDS)
    validate_zone_intervals(rows, manifest_rows, require_reviewed=require_reviewed)
    return rows
