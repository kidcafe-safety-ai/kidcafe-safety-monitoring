"""실제 RGB 외부 데이터 cohort의 공통 I/O와 provenance 검증 도구."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import os
import shutil
import subprocess
from fractions import Fraction
from pathlib import Path, PurePosixPath
from typing import Iterable, Mapping, Sequence


COHORT_SCHEMA_VERSION = "real_rgb_fall_cohort_v1"
COHORT_MANIFEST = "cohort_manifest.json"
ANNOTATION_FIELDS = (
    "video_id",
    "label",
    "video_path",
    "fall_start_frame",
    "impact_frame",
    "lying_start_frame",
    "review_status",
    "dataset_fall_label_frame",
)


class CohortError(ValueError):
    """입력 데이터나 생성 결과가 cohort 계약을 만족하지 않을 때 발생한다."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as file:
        for chunk in iter(lambda: file.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def md5_file(path: Path) -> str:
    digest = hashlib.md5()  # noqa: S324 - official archive integrity metadata
    with open(path, "rb") as file:
        for chunk in iter(lambda: file.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_relative_video_path(value: object) -> Path:
    if not isinstance(value, str) or not value or "\\" in value:
        raise CohortError(f"유효하지 않은 video_path입니다: {value!r}")
    pure = PurePosixPath(value)
    if (
        pure.is_absolute()
        or ".." in pure.parts
        or "." in pure.parts
        or len(pure.parts) < 2
        or pure.parts[0] != "videos"
        or pure.suffix.lower() != ".mp4"
    ):
        raise CohortError(f"안전하지 않은 video_path입니다: {value!r}")
    return Path(*pure.parts)


def render_annotations(rows: Iterable[Mapping[str, object]]) -> str:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(
        output,
        fieldnames=ANNOTATION_FIELDS,
        lineterminator="\n",
        extrasaction="ignore",
    )
    writer.writeheader()
    count = 0
    for row in rows:
        writer.writerow({field: row.get(field, "") for field in ANNOTATION_FIELDS})
        count += 1
    if count == 0:
        raise CohortError("annotation 행이 비어 있습니다.")
    return output.getvalue()


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as file:
        file.write(content)
        file.flush()
        os.fsync(file.fileno())


def write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)
        file.write("\n")
        file.flush()
        os.fsync(file.fileno())


def parse_rate(value: object) -> float:
    try:
        rate = float(Fraction(str(value)))
    except (ValueError, ZeroDivisionError) as exc:
        raise CohortError(f"유효하지 않은 frame rate입니다: {value!r}") from exc
    if not math.isfinite(rate) or rate <= 0:
        raise CohortError(f"유효하지 않은 frame rate입니다: {value!r}")
    return rate


def probe_video(path: Path, ffprobe: str) -> dict:
    command = [
        ffprobe,
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=codec_name,width,height,avg_frame_rate,nb_frames:format=duration",
        "-of",
        "json",
        str(path),
    ]
    try:
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(result.stdout)
        stream = payload["streams"][0]
        duration = float(payload["format"]["duration"])
        width = int(stream["width"])
        height = int(stream["height"])
        frame_count = int(stream["nb_frames"])
    except (
        subprocess.CalledProcessError,
        json.JSONDecodeError,
        KeyError,
        IndexError,
        TypeError,
        ValueError,
    ) as exc:
        stderr = getattr(exc, "stderr", "") or ""
        raise CohortError(f"ffprobe 검증 실패: {path}: {stderr.strip()}") from exc
    if (
        duration <= 0
        or not math.isfinite(duration)
        or width <= 0
        or height <= 0
        or frame_count <= 0
    ):
        raise CohortError(f"영상 metadata가 올바르지 않습니다: {path}")
    return {
        "codec_name": stream.get("codec_name"),
        "width": width,
        "height": height,
        "fps": parse_rate(stream["avg_frame_rate"]),
        "duration_sec": duration,
        "frame_count": frame_count,
    }


def require_tools(*tools: str) -> None:
    missing = [tool for tool in tools if shutil.which(tool) is None]
    if missing:
        raise CohortError(f"실행 파일이 필요합니다: {', '.join(missing)}")


def replace_output(staging_dir: Path, output_dir: Path, force: bool) -> None:
    if output_dir.exists() and not force:
        raise CohortError(f"{output_dir}가 이미 있습니다 (--force로 전체 교체).")
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


def annotation_manifest(
    staging_dir: Path,
    annotation_rows: Mapping[str, Sequence[Mapping[str, object]]],
) -> dict:
    result = {}
    for split_role, rows in sorted(annotation_rows.items()):
        filename = f"annotations_{split_role}.csv"
        path = staging_dir / filename
        write_text(path, render_annotations(rows))
        result[split_role] = {
            "path": filename,
            "row_count": len(rows),
            "sha256": sha256_file(path),
        }
    return result
