"""검증된 영상 cohort를 OpenCV 호환 H.264 MP4로 변환한다.

OmniFall OF-Synthetic 원본은 AV1이므로 OpenCV 빌드에 따라 디코딩되지 않을
수 있다. 이 도구는 materialized cohort의 checksum을 먼저 검증하고, 원본을
보존한 채 별도 디렉터리에 H.264/yuv420p 변환본과 provenance manifest를 쓴다.

Usage:
    python scripts/transcode_video_cohort.py \
        --source-dir /content/phase4_a2/omnifall_e1_cohort \
        --output-dir /content/phase4_a2/omnifall_e1_cohort_h264
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import subprocess
import tempfile
from fractions import Fraction
from pathlib import Path, PurePosixPath
from typing import Mapping


SOURCE_SCHEMA_VERSION = "omnifall_e0_mining_cohort_v1"
TRANSCODE_SCHEMA_VERSION = "video_cohort_transcode_v1"
SOURCE_MANIFEST = "cohort_manifest.json"
ANNOTATIONS_CSV = "annotations.csv"
TRANSCODE_MANIFEST = "transcode_manifest.json"


class TranscodeError(ValueError):
    """입력 cohort 또는 변환 결과가 계약을 만족하지 않을 때 발생한다."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--ffprobe", default="ffprobe")
    parser.add_argument("--crf", type=int, default=18)
    parser.add_argument("--preset", default="veryfast")
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as file:
        for chunk in iter(lambda: file.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_relative_video_path(value: object) -> Path:
    if not isinstance(value, str) or not value:
        raise TranscodeError("cohort manifest의 video_path가 비어 있습니다.")
    if "\\" in value:
        raise TranscodeError(f"video_path는 '/'를 사용해야 합니다: {value!r}")
    pure = PurePosixPath(value)
    if (
        pure.is_absolute()
        or ".." in pure.parts
        or "." in pure.parts
        or not pure.parts
        or pure.parts[0] != "videos"
        or pure.suffix.lower() != ".mp4"
    ):
        raise TranscodeError(f"안전하지 않은 video_path입니다: {value!r}")
    return Path(*pure.parts)


def _load_and_validate_source(source_dir: Path) -> tuple[dict, list[dict]]:
    manifest_path = source_dir / SOURCE_MANIFEST
    annotations_path = source_dir / ANNOTATIONS_CSV
    if not manifest_path.is_file() or not annotations_path.is_file():
        raise TranscodeError(
            f"{source_dir}에 {SOURCE_MANIFEST}와 {ANNOTATIONS_CSV}가 필요합니다."
        )
    try:
        with open(manifest_path, "r", encoding="utf-8") as file:
            manifest = json.load(file)
    except (OSError, json.JSONDecodeError) as exc:
        raise TranscodeError(f"cohort manifest를 읽을 수 없습니다: {exc}") from exc
    if manifest.get("schema_version") != SOURCE_SCHEMA_VERSION:
        raise TranscodeError(
            "지원하지 않는 source schema_version입니다: "
            f"{manifest.get('schema_version')!r}"
        )
    if manifest.get("annotations_sha256") != _sha256(annotations_path):
        raise TranscodeError("annotations.csv SHA-256이 cohort manifest와 다릅니다.")

    records = manifest.get("videos")
    if not isinstance(records, list) or not records:
        raise TranscodeError("cohort manifest의 videos가 비어 있습니다.")
    if manifest.get("video_count") != len(records):
        raise TranscodeError("cohort manifest의 video_count가 videos 수와 다릅니다.")

    seen_paths = set()
    for record in records:
        if not isinstance(record, dict):
            raise TranscodeError("cohort manifest의 video record가 객체가 아닙니다.")
        relative_path = _safe_relative_video_path(record.get("video_path"))
        if relative_path in seen_paths:
            raise TranscodeError(f"video_path가 중복됩니다: {relative_path}")
        seen_paths.add(relative_path)
        source_path = source_dir / relative_path
        if not source_path.is_file():
            raise TranscodeError(f"source 영상이 없습니다: {source_path}")
        if record.get("size_bytes") != source_path.stat().st_size:
            raise TranscodeError(f"source 영상 크기가 manifest와 다릅니다: {source_path}")
        if record.get("sha256") != _sha256(source_path):
            raise TranscodeError(f"source 영상 SHA-256이 다릅니다: {source_path}")
    return manifest, records


def _parse_rate(value: object) -> float:
    try:
        rate = float(Fraction(str(value)))
    except (ValueError, ZeroDivisionError) as exc:
        raise TranscodeError(f"유효하지 않은 video frame rate입니다: {value!r}") from exc
    if not math.isfinite(rate) or rate <= 0:
        raise TranscodeError(f"유효하지 않은 video frame rate입니다: {value!r}")
    return rate


def _probe_video(path: Path, ffprobe: str) -> dict:
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
            command, check=True, capture_output=True, text=True
        )
        payload = json.loads(result.stdout)
        stream = payload["streams"][0]
        duration = float(payload["format"]["duration"])
    except (subprocess.CalledProcessError, json.JSONDecodeError, KeyError,
            IndexError, TypeError, ValueError) as exc:
        stderr = getattr(exc, "stderr", "") or ""
        raise TranscodeError(f"ffprobe 검증 실패: {path}: {stderr.strip()}") from exc
    if duration <= 0 or not math.isfinite(duration):
        raise TranscodeError(f"유효하지 않은 video duration입니다: {path}")
    return {
        "codec_name": stream.get("codec_name"),
        "width": int(stream["width"]),
        "height": int(stream["height"]),
        "fps": _parse_rate(stream["avg_frame_rate"]),
        "duration_sec": duration,
        "frame_count": stream.get("nb_frames"),
    }


def _run_transcode(
    source: Path,
    destination: Path,
    ffmpeg: str,
    crf: int,
    preset: str,
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.stem}.part.mp4")
    command = [
        ffmpeg,
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(source),
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
        str(temporary),
    ]
    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
        os.replace(temporary, destination)
    except subprocess.CalledProcessError as exc:
        temporary.unlink(missing_ok=True)
        raise TranscodeError(
            f"ffmpeg 변환 실패: {source}: {(exc.stderr or '').strip()}"
        ) from exc


def _validate_equivalence(source: Mapping[str, object], output: Mapping[str, object]) -> None:
    if output["codec_name"] != "h264":
        raise TranscodeError(f"출력 codec이 h264가 아닙니다: {output['codec_name']!r}")
    if (source["width"], source["height"]) != (
        output["width"],
        output["height"],
    ):
        raise TranscodeError("변환 전후 해상도가 다릅니다.")
    if not math.isclose(float(source["fps"]), float(output["fps"]), rel_tol=1e-4):
        raise TranscodeError("변환 전후 FPS가 다릅니다.")
    frame_period = 1.0 / float(source["fps"])
    if abs(float(source["duration_sec"]) - float(output["duration_sec"])) > max(
        0.1, frame_period
    ):
        raise TranscodeError("변환 전후 duration 차이가 허용 범위를 넘습니다.")
    source_frames = source.get("frame_count")
    output_frames = output.get("frame_count")
    if source_frames not in (None, "N/A") and output_frames not in (None, "N/A"):
        if int(source_frames) != int(output_frames):
            raise TranscodeError("변환 전후 frame 수가 다릅니다.")


def _replace_output(staging_dir: Path, output_dir: Path, force: bool) -> None:
    if output_dir.exists() and not force:
        raise TranscodeError(f"{output_dir}가 이미 있습니다 (--force로 전체 교체).")
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


def transcode_cohort(
    source_dir: Path,
    output_dir: Path,
    ffmpeg: str,
    ffprobe: str,
    crf: int,
    preset: str,
    force: bool,
) -> dict:
    if not 0 <= crf <= 51:
        raise TranscodeError("--crf는 0 이상 51 이하여야 합니다.")
    if output_dir.exists() and not force:
        raise TranscodeError(f"{output_dir}가 이미 있습니다 (--force로 전체 교체).")
    if shutil.which(ffmpeg) is None or shutil.which(ffprobe) is None:
        raise TranscodeError("ffmpeg와 ffprobe 실행 파일이 필요합니다.")

    source_manifest, source_records = _load_and_validate_source(source_dir)
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    staging_dir = Path(
        tempfile.mkdtemp(prefix=f".{output_dir.name}.build-", dir=output_dir.parent)
    )
    output_records = []
    try:
        total = len(source_records)
        for index, source_record in enumerate(source_records, start=1):
            relative_path = _safe_relative_video_path(source_record["video_path"])
            source_path = source_dir / relative_path
            output_path = staging_dir / relative_path
            source_probe = _probe_video(source_path, ffprobe)
            _run_transcode(source_path, output_path, ffmpeg, crf, preset)
            output_probe = _probe_video(output_path, ffprobe)
            _validate_equivalence(source_probe, output_probe)
            output_records.append(
                {
                    "video_id": source_record.get("video_id"),
                    "video_path": relative_path.as_posix(),
                    "source_sha256": source_record["sha256"],
                    "output_sha256": _sha256(output_path),
                    "output_size_bytes": output_path.stat().st_size,
                    "source_probe": source_probe,
                    "output_probe": output_probe,
                }
            )
            if index % 25 == 0 or index == total:
                print(f"H.264 변환 {index}/{total}")

        shutil.copyfile(
            source_dir / ANNOTATIONS_CSV, staging_dir / ANNOTATIONS_CSV
        )
        manifest = {
            "schema_version": TRANSCODE_SCHEMA_VERSION,
            "source_dir": str(source_dir),
            "source_manifest_sha256": _sha256(source_dir / SOURCE_MANIFEST),
            "source_annotations_sha256": source_manifest["annotations_sha256"],
            "output_annotations_sha256": _sha256(staging_dir / ANNOTATIONS_CSV),
            "video_count": len(output_records),
            "encoder": "libx264",
            "pixel_format": "yuv420p",
            "crf": crf,
            "preset": preset,
            "videos": output_records,
        }
        with open(staging_dir / TRANSCODE_MANIFEST, "w", encoding="utf-8") as file:
            json.dump(manifest, file, ensure_ascii=False, indent=2)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        _replace_output(staging_dir, output_dir, force)
        return manifest
    except Exception:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise


def main() -> None:
    args = parse_args()
    try:
        manifest = transcode_cohort(
            Path(args.source_dir),
            Path(args.output_dir),
            args.ffmpeg,
            args.ffprobe,
            args.crf,
            args.preset,
            args.force,
        )
    except TranscodeError as exc:
        raise SystemExit(str(exc)) from exc
    print(
        f"H.264 cohort: {manifest['video_count']} videos -> {args.output_dir}"
    )


if __name__ == "__main__":
    main()
