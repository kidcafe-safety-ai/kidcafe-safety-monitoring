"""사람이 완료한 실제 RGB false Event 검수본을 검증하고 불변 파일로 동결한다."""

from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import sys
import tempfile
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from materialize_real_rgb_false_event_review import (  # noqa: E402
    REVIEW_DECISIONS,
    REVIEW_MANIFEST,
    REVIEW_SCHEMA_VERSION,
)
from real_rgb_cohort import replace_output, sha256_file, write_json  # noqa: E402


FROZEN_SCHEMA_VERSION = "real_rgb_false_event_review_frozen_v1"
FROZEN_CSV = "review_frozen.csv"
FROZEN_MANIFEST = "review_frozen_manifest.json"
REVIEW_STATUSES = {"reviewed", "needs_review"}
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
REQUIRED_COLUMNS = {
    "review_id",
    "source_dataset",
    "video_id",
    "review_status",
    "review_decision",
    "selected_for_training",
    "reviewer_id",
}


class FreezeReviewError(ValueError):
    """검수본이나 검수 package가 동결 계약을 만족하지 않을 때 발생한다."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review-dir", required=True)
    parser.add_argument("--completed-review-csv", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def _load_json(path: Path) -> dict:
    if not path.is_file():
        raise FreezeReviewError(f"검수 manifest가 없습니다: {path}")
    try:
        with open(path, "r", encoding="utf-8") as file:
            payload = json.load(file)
    except (OSError, json.JSONDecodeError) as exc:
        raise FreezeReviewError(f"검수 manifest를 읽을 수 없습니다: {exc}") from exc
    if not isinstance(payload, dict):
        raise FreezeReviewError("검수 manifest root는 객체여야 합니다.")
    return payload


def _parse_bool(value: object, row_number: int) -> bool:
    normalized = str(value).strip().lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise FreezeReviewError(
        f"완료 CSV {row_number}행 selected_for_training은 true/false여야 합니다."
    )


def _load_completed_rows(path: Path) -> tuple[list[dict], list[str]]:
    if not path.is_file():
        raise FreezeReviewError(f"완료 검수 CSV가 없습니다: {path}")
    with open(path, "r", encoding="utf-8", newline="") as file:
        reader = csv.DictReader(file)
        fieldnames = list(reader.fieldnames or [])
        missing = REQUIRED_COLUMNS - set(fieldnames)
        if missing:
            raise FreezeReviewError(
                f"완료 검수 CSV 필수 컬럼이 없습니다: {sorted(missing)}"
            )
        rows = list(reader)
    if not rows:
        raise FreezeReviewError("완료 검수 CSV가 비어 있습니다.")
    return rows, fieldnames


def validate_review(
    review_dir: Path,
    completed_review_csv: Path,
) -> tuple[list[dict], list[str], dict]:
    manifest = _load_json(review_dir / REVIEW_MANIFEST)
    if manifest.get("schema_version") != REVIEW_SCHEMA_VERSION:
        raise FreezeReviewError("지원하지 않는 review schema_version입니다.")
    clips = manifest.get("clips")
    if not isinstance(clips, list) or manifest.get("clip_count") != len(clips):
        raise FreezeReviewError("검수 manifest의 clips/clip_count가 올바르지 않습니다.")

    expected = {}
    for clip in clips:
        if not isinstance(clip, dict):
            raise FreezeReviewError("검수 manifest의 clip record가 객체가 아닙니다.")
        review_id = clip.get("review_id")
        clip_path = clip.get("clip_path")
        clip_sha256 = clip.get("clip_sha256")
        if not isinstance(review_id, str) or not review_id or review_id in expected:
            raise FreezeReviewError(f"review_id가 비었거나 중복됩니다: {review_id!r}")
        if not isinstance(clip_path, str) or not clip_path:
            raise FreezeReviewError(f"clip_path가 비었습니다: {review_id}")
        if not isinstance(clip_sha256, str) or not SHA256_PATTERN.fullmatch(
            clip_sha256
        ):
            raise FreezeReviewError(f"clip SHA-256이 올바르지 않습니다: {review_id}")
        path = review_dir / clip_path
        if not path.is_file() or sha256_file(path) != clip_sha256:
            raise FreezeReviewError(f"검수 clip이 없거나 변경됐습니다: {review_id}")
        expected[review_id] = clip

    rows, fieldnames = _load_completed_rows(completed_review_csv)
    normalized = []
    seen = set()
    for row_number, row in enumerate(rows, start=2):
        review_id = (row.get("review_id") or "").strip()
        if review_id not in expected or review_id in seen:
            raise FreezeReviewError(
                f"완료 CSV {row_number}행 review_id가 없거나 중복됩니다: {review_id!r}"
            )
        seen.add(review_id)
        if (row.get("source_dataset") or "").strip() != manifest.get(
            "source_dataset"
        ):
            raise FreezeReviewError(f"source_dataset이 다릅니다: {review_id}")
        if (row.get("video_id") or "").strip() != expected[review_id].get("video_id"):
            raise FreezeReviewError(f"video_id가 다릅니다: {review_id}")

        status = (row.get("review_status") or "").strip()
        decision = (row.get("review_decision") or "").strip()
        reviewer_id = (row.get("reviewer_id") or "").strip()
        selected = _parse_bool(row.get("selected_for_training"), row_number)
        if status not in REVIEW_STATUSES:
            raise FreezeReviewError(
                f"검수 상태는 reviewed/needs_review여야 합니다: {review_id}"
            )
        if not reviewer_id:
            raise FreezeReviewError(f"reviewer_id가 비었습니다: {review_id}")
        if status == "reviewed" and decision not in REVIEW_DECISIONS:
            raise FreezeReviewError(f"검수 판정이 올바르지 않습니다: {review_id}")
        if status == "needs_review" and decision not in {"", "ambiguous"}:
            raise FreezeReviewError(
                f"needs_review 행은 빈 판정 또는 ambiguous여야 합니다: {review_id}"
            )
        if selected and not (status == "reviewed" and decision == "hard_negative"):
            raise FreezeReviewError(
                f"학습 선택은 reviewed hard_negative만 가능합니다: {review_id}"
            )
        normalized.append(
            {
                **row,
                "review_id": review_id,
                "review_status": status,
                "review_decision": decision,
                "selected_for_training": "true" if selected else "false",
                "reviewer_id": reviewer_id,
            }
        )
    if seen != set(expected):
        missing = sorted(set(expected) - seen)
        raise FreezeReviewError(
            f"완료 CSV에 검수 package 행이 누락됐습니다: {missing[:5]}"
        )
    return normalized, fieldnames, manifest


def freeze_review(
    review_dir: Path,
    completed_review_csv: Path,
    output_dir: Path,
    force: bool,
) -> dict:
    if output_dir.exists() and not force:
        raise FreezeReviewError(f"{output_dir}가 이미 있습니다 (--force로 전체 교체).")
    rows, fieldnames, source_manifest = validate_review(
        review_dir, completed_review_csv
    )
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(prefix=f".{output_dir.name}.build-", dir=output_dir.parent)
    )
    try:
        frozen_csv = staging / FROZEN_CSV
        with open(frozen_csv, "w", encoding="utf-8", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=fieldnames, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
        frozen_sha256 = sha256_file(frozen_csv)
        status_counts = Counter(row["review_status"] for row in rows)
        decision_counts = Counter(
            row["review_decision"] or "unresolved" for row in rows
        )
        selected_rows = [
            row for row in rows if row["selected_for_training"] == "true"
        ]
        manifest = {
            "schema_version": FROZEN_SCHEMA_VERSION,
            "source_review_schema_version": source_manifest["schema_version"],
            "source_dataset": source_manifest["source_dataset"],
            "source_review_manifest_sha256": sha256_file(review_dir / REVIEW_MANIFEST),
            "completed_review_csv_sha256": sha256_file(completed_review_csv),
            "frozen_review_csv": FROZEN_CSV,
            "frozen_review_csv_sha256": frozen_sha256,
            "review_count": len(rows),
            "review_status_counts": dict(sorted(status_counts.items())),
            "review_decision_counts": dict(sorted(decision_counts.items())),
            "selected_for_training_count": len(selected_rows),
            "selected_video_count": len({row["video_id"] for row in selected_rows}),
        }
        write_json(staging / FROZEN_MANIFEST, manifest)
        replace_output(staging, output_dir, force)
        return manifest
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def main() -> None:
    args = parse_args()
    try:
        manifest = freeze_review(
            Path(args.review_dir),
            Path(args.completed_review_csv),
            Path(args.output_dir),
            args.force,
        )
    except FreezeReviewError as exc:
        raise SystemExit(str(exc)) from exc
    print(
        "실제 RGB 검수 동결: "
        f"{manifest['review_count']} rows, "
        f"{manifest['selected_for_training_count']} selected -> {args.output_dir}"
    )
    print(f"frozen SHA-256: {manifest['frozen_review_csv_sha256']}")


if __name__ == "__main__":
    main()
