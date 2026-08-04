"""OmniFall false Event를 사람이 검수할 짧은 H.264 clip으로 만든다.

``analyze_omnifall_false_events.py``의 결과와 검증된 H.264 cohort를 입력으로
받아 Event 전후 구간만 다시 인코딩한다. 출력 ``review.csv``는 검수 전용이며,
``review_status=reviewed``와 ``selected_for_training=true``가 되기 전에는 학습
입력으로 사용하지 않는다.

Usage:
    python scripts/materialize_omnifall_false_event_review.py \
        --analysis-dir /content/drive/MyDrive/kidcafe-data/phase4/results/\
omnifall_e1_false_event_analysis \
        --cohort-dir /content/phase4_a2/omnifall_e1_cohort_h264 \
        --output-dir /content/drive/MyDrive/kidcafe-data/phase4/review/\
omnifall_e1_false_events
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path, PurePosixPath
from typing import Dict, List, Sequence


ANALYSIS_SCHEMA_VERSION = "omnifall_false_event_analysis_v1"
TRANSCODE_SCHEMA_VERSION = "video_cohort_transcode_v1"
REVIEW_SCHEMA_VERSION = "omnifall_false_event_review_v1"
ANALYSIS_CSV = "false_events.csv"
ANALYSIS_JSON = "false_event_analysis.json"
TRANSCODE_MANIFEST = "transcode_manifest.json"
REVIEW_CSV = "review.csv"
REVIEW_MANIFEST = "review_manifest.json"
CLIPS_DIR = "clips"
REVIEW_DECISIONS = {
    "hard_negative",
    "synthetic_artifact",
    "tracking_error",
    "label_error",
    "ambiguous",
}
REQUIRED_COLUMNS = {
    "review_id",
    "video_id",
    "event_frame",
    "event_sec",
    "review_start_sec",
    "review_end_sec",
    "confirm_path",
    "candidate_entry_reason",
    "active_labels",
}
_SAFE_REVIEW_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


class ReviewPackageError(ValueError):
    """분석 결과, cohort 또는 clip 출력이 계약을 만족하지 않을 때 발생한다."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analysis-dir", required=True)
    parser.add_argument("--cohort-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--crf", type=int, default=20)
    parser.add_argument("--preset", default="veryfast")
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as file:
        for chunk in iter(lambda: file.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path, description: str) -> dict:
    if not path.is_file():
        raise ReviewPackageError(f"{description} 파일이 없습니다: {path}")
    try:
        with open(path, "r", encoding="utf-8") as file:
            payload = json.load(file)
    except (OSError, json.JSONDecodeError) as exc:
        raise ReviewPackageError(f"{description} JSON을 읽을 수 없습니다: {exc}") from exc
    if not isinstance(payload, dict):
        raise ReviewPackageError(f"{description} JSON root는 객체여야 합니다.")
    return payload


def _safe_video_path(value: object) -> Path:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ReviewPackageError(f"video_path가 올바르지 않습니다: {value!r}")
    pure = PurePosixPath(value)
    if (
        pure.is_absolute()
        or ".." in pure.parts
        or "." in pure.parts
        or not pure.parts
        or pure.parts[0] != "videos"
        or pure.suffix.lower() != ".mp4"
    ):
        raise ReviewPackageError(f"안전하지 않은 video_path입니다: {value!r}")
    return Path(*pure.parts)


def load_analysis(analysis_dir: Path) -> tuple[List[dict], dict]:
    csv_path = analysis_dir / ANALYSIS_CSV
    manifest = _load_json(analysis_dir / ANALYSIS_JSON, "analysis manifest")
    if manifest.get("schema_version") != ANALYSIS_SCHEMA_VERSION:
        raise ReviewPackageError("지원하지 않는 analysis schema_version입니다.")
    if not csv_path.is_file():
        raise ReviewPackageError(f"analysis CSV가 없습니다: {csv_path}")
    if manifest.get("false_events_csv_sha256") != _sha256(csv_path):
        raise ReviewPackageError("false_events.csv SHA-256이 manifest와 다릅니다.")

    with open(csv_path, "r", encoding="utf-8", newline="") as file:
        reader = csv.DictReader(file)
        missing = REQUIRED_COLUMNS - set(reader.fieldnames or [])
        if missing:
            raise ReviewPackageError(
                f"false_events.csv 필수 컬럼이 없습니다: {sorted(missing)}"
            )
        rows = list(reader)
    if not rows:
        raise ReviewPackageError("false_events.csv가 비어 있습니다.")
    summary = manifest.get("summary")
    if (
        not isinstance(summary, dict)
        or summary.get("false_event_count") != len(rows)
    ):
        raise ReviewPackageError(
            "analysis summary의 false_event_count가 CSV 행 수와 다릅니다."
        )

    seen = set()
    normalized = []
    for row_number, row in enumerate(rows, start=2):
        review_id = (row.get("review_id") or "").strip()
        video_id = (row.get("video_id") or "").strip()
        if not _SAFE_REVIEW_ID.fullmatch(review_id):
            raise ReviewPackageError(
                f"false_events.csv {row_number}행 review_id가 안전하지 않습니다."
            )
        if review_id in seen:
            raise ReviewPackageError(f"review_id가 중복됩니다: {review_id}")
        seen.add(review_id)
        if not video_id:
            raise ReviewPackageError(
                f"false_events.csv {row_number}행 video_id가 비어 있습니다."
            )
        try:
            event_sec = float(row["event_sec"])
            start_sec = float(row["review_start_sec"])
            end_sec = float(row["review_end_sec"])
            event_frame = int(row["event_frame"])
        except (TypeError, ValueError) as exc:
            raise ReviewPackageError(
                f"false_events.csv {row_number}행 시각/frame이 올바르지 않습니다."
            ) from exc
        if not all(math.isfinite(value) for value in (event_sec, start_sec, end_sec)):
            raise ReviewPackageError(
                f"false_events.csv {row_number}행 시각이 유한하지 않습니다."
            )
        if start_sec < 0 or end_sec <= start_sec or not start_sec <= event_sec <= end_sec:
            raise ReviewPackageError(
                f"false_events.csv {row_number}행 검수 구간이 올바르지 않습니다."
            )
        if event_frame < 0:
            raise ReviewPackageError(
                f"false_events.csv {row_number}행 event_frame이 음수입니다."
            )
        normalized.append(
            {
                **row,
                "review_id": review_id,
                "video_id": video_id,
                "event_frame": event_frame,
                "event_sec": event_sec,
                "review_start_sec": start_sec,
                "review_end_sec": end_sec,
            }
        )
    return normalized, manifest


def load_cohort(cohort_dir: Path) -> tuple[Dict[str, dict], Path]:
    manifest_path = cohort_dir / TRANSCODE_MANIFEST
    manifest = _load_json(manifest_path, "transcode manifest")
    if manifest.get("schema_version") != TRANSCODE_SCHEMA_VERSION:
        raise ReviewPackageError("지원하지 않는 transcode schema_version입니다.")
    records = manifest.get("videos")
    if not isinstance(records, list) or manifest.get("video_count") != len(records):
        raise ReviewPackageError("transcode manifest videos/video_count가 올바르지 않습니다.")

    by_id = {}
    seen_paths = set()
    for record in records:
        if not isinstance(record, dict):
            raise ReviewPackageError("transcode video record가 객체가 아닙니다.")
        video_id = record.get("video_id")
        if not isinstance(video_id, str) or not video_id or video_id in by_id:
            raise ReviewPackageError(f"video_id가 비었거나 중복됩니다: {video_id!r}")
        relative_path = _safe_video_path(record.get("video_path"))
        if relative_path in seen_paths:
            raise ReviewPackageError(f"video_path가 중복됩니다: {relative_path}")
        seen_paths.add(relative_path)
        source_path = cohort_dir / relative_path
        if not source_path.is_file():
            raise ReviewPackageError(f"H.264 cohort 영상이 없습니다: {source_path}")
        if record.get("output_sha256") != _sha256(source_path):
            raise ReviewPackageError(f"H.264 영상 SHA-256이 다릅니다: {source_path}")
        probe = record.get("output_probe")
        duration = probe.get("duration_sec") if isinstance(probe, dict) else None
        if (
            not isinstance(duration, (int, float))
            or not math.isfinite(duration)
            or duration <= 0
        ):
            raise ReviewPackageError(f"영상 duration이 올바르지 않습니다: {video_id}")
        by_id[video_id] = {
            "path": source_path,
            "relative_path": relative_path.as_posix(),
            "duration_sec": float(duration),
        }
    return by_id, manifest_path


def _run_clip(
    source: Path,
    destination: Path,
    start_sec: float,
    duration_sec: float,
    ffmpeg: str,
    crf: int,
    preset: str,
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    command = [
        ffmpeg,
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(source),
        "-ss",
        f"{start_sec:.6f}",
        "-t",
        f"{duration_sec:.6f}",
        "-map",
        "0:v:0",
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        preset,
        "-crf",
        str(crf),
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(destination),
    ]
    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        raise ReviewPackageError(
            f"검수 clip 생성 실패: {source}: {(exc.stderr or '').strip()}"
        ) from exc
    if not destination.is_file() or destination.stat().st_size == 0:
        raise ReviewPackageError(f"검수 clip이 비어 있습니다: {destination}")


def _review_csv(records: Sequence[dict]) -> str:
    source_fields = [
        "review_id",
        "video_id",
        "event_frame",
        "event_sec",
        "review_start_sec",
        "review_end_sec",
        "event_offset_sec",
        "active_labels",
        "confirm_path",
        "candidate_entry_reason",
        "diagnostic_route",
        "clip_path",
    ]
    review_fields = [
        "review_status",
        "review_decision",
        "selected_for_training",
        "reviewer_id",
        "notes",
    ]
    fields = source_fields + review_fields
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for record in records:
        writer.writerow({field: record.get(field, "") for field in fields})
    return output.getvalue()


def _replace_output(staging_dir: Path, output_dir: Path, force: bool) -> None:
    if output_dir.exists() and not force:
        raise ReviewPackageError(f"{output_dir}가 이미 있습니다 (--force로 전체 교체).")
    backup = output_dir.with_name(f".{output_dir.name}.backup-{os.getpid()}")
    if output_dir.exists():
        output_dir.rename(backup)
    try:
        staging_dir.rename(output_dir)
    except Exception:
        if backup.exists() and not output_dir.exists():
            backup.rename(output_dir)
        raise
    shutil.rmtree(backup, ignore_errors=True)


def materialize_review(
    analysis_dir: Path,
    cohort_dir: Path,
    output_dir: Path,
    ffmpeg: str,
    crf: int,
    preset: str,
    force: bool,
) -> dict:
    if not 0 <= crf <= 51:
        raise ReviewPackageError("--crf는 0 이상 51 이하여야 합니다.")
    if shutil.which(ffmpeg) is None:
        raise ReviewPackageError("ffmpeg 실행 파일이 필요합니다.")
    if output_dir.exists() and not force:
        raise ReviewPackageError(f"{output_dir}가 이미 있습니다 (--force로 전체 교체).")
    records, analysis_manifest = load_analysis(analysis_dir)
    cohort, transcode_manifest_path = load_cohort(cohort_dir)

    output_dir.parent.mkdir(parents=True, exist_ok=True)
    staging_dir = Path(
        tempfile.mkdtemp(prefix=f".{output_dir.name}.build-", dir=output_dir.parent)
    )
    output_records = []
    try:
        total = len(records)
        for index, record in enumerate(records, start=1):
            source = cohort.get(record["video_id"])
            if source is None:
                raise ReviewPackageError(
                    f"H.264 cohort에 video_id가 없습니다: {record['video_id']}"
                )
            if record["review_end_sec"] > source["duration_sec"] + 0.05:
                raise ReviewPackageError(
                    f"검수 구간이 영상 duration을 넘습니다: {record['review_id']}"
                )
            relative_clip = Path(CLIPS_DIR) / f"{record['review_id']}.mp4"
            clip_path = staging_dir / relative_clip
            duration_sec = record["review_end_sec"] - record["review_start_sec"]
            _run_clip(
                source["path"],
                clip_path,
                record["review_start_sec"],
                duration_sec,
                ffmpeg,
                crf,
                preset,
            )
            output_records.append(
                {
                    **record,
                    "event_offset_sec": round(
                        record["event_sec"] - record["review_start_sec"], 6
                    ),
                    "clip_path": relative_clip.as_posix(),
                    "review_status": "pending",
                    "review_decision": "",
                    "selected_for_training": "false",
                    "reviewer_id": "",
                    "notes": "",
                    "clip_sha256": _sha256(clip_path),
                    "source_video_path": source["relative_path"],
                }
            )
            if index % 20 == 0 or index == total:
                print(f"검수 clip 생성 {index}/{total}")

        review_content = _review_csv(output_records)
        review_path = staging_dir / REVIEW_CSV
        review_path.write_text(review_content, encoding="utf-8", newline="")
        manifest = {
            "schema_version": REVIEW_SCHEMA_VERSION,
            "purpose": "manual review; not direct training input",
            "analysis_manifest_sha256": _sha256(analysis_dir / ANALYSIS_JSON),
            "analysis_csv_sha256": analysis_manifest["false_events_csv_sha256"],
            "transcode_manifest_sha256": _sha256(transcode_manifest_path),
            "clip_count": len(output_records),
            "review_csv_sha256": _sha256(review_path),
            "review_decisions": sorted(REVIEW_DECISIONS),
            "encoder": "libx264",
            "pixel_format": "yuv420p",
            "crf": crf,
            "preset": preset,
            "clips": [
                {
                    "review_id": record["review_id"],
                    "video_id": record["video_id"],
                    "clip_path": record["clip_path"],
                    "clip_sha256": record["clip_sha256"],
                    "source_video_path": record["source_video_path"],
                }
                for record in output_records
            ],
        }
        manifest_path = staging_dir / REVIEW_MANIFEST
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        _replace_output(staging_dir, output_dir, force)
        return manifest
    except Exception:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise


def main() -> None:
    args = parse_args()
    try:
        manifest = materialize_review(
            Path(args.analysis_dir),
            Path(args.cohort_dir),
            Path(args.output_dir),
            args.ffmpeg,
            args.crf,
            args.preset,
            args.force,
        )
    except ReviewPackageError as exc:
        raise SystemExit(str(exc)) from exc
    print(
        f"OmniFall false Event 검수 패키지: {manifest['clip_count']} clips "
        f"-> {args.output_dir}"
    )


if __name__ == "__main__":
    main()
