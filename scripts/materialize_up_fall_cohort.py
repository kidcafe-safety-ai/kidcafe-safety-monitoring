"""UP-Fall PNG ZIP을 subject-disjoint 실제 RGB H.264 cohort로 만든다.

Phase 4 A2에서는 공식 UP-Fall Camera 1, Trial 1의 ADL 3종(sitting,
picking-up, laying)과 Fall 5종(forward-hands, forward-knees, backward,
sideward, sitting-fall)을 사용한다. Subject 1-8은 검수 후 학습 후보이고
Subject 9-10은 독립 validation이다. ZIP 전체를 풀지 않고 frame을 ffmpeg
stdin으로 보내므로 원본 PNG와 변환본이 동시에 디스크를 점유하지 않는다.

UP-Fall은 GMDCSA24와 달리 공식 onset/impact 타임스탬프 CSV를 제공하지
않는다(원 논문: fall trial은 카메라 영상을 육안 검수로만 태깅). 그래서 Fall
라벨 영상은 review_status=needs_review·프레임 필드 공란으로 생성하고,
fall_start_frame·impact_frame·lying_start_frame은 사람이 직접 검수해
CAUCAFall과 동일한 CSV 스키마로 채운 뒤 review_status=reviewed로 바꿔야
evaluate_fall.py 기본 평가에 포함된다.
"""

from __future__ import annotations

import argparse
import csv
import math
import re
import shutil
import struct
import subprocess
import tempfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Mapping
from zipfile import BadZipFile, ZipFile, ZipInfo

from real_rgb_cohort import (
    COHORT_MANIFEST,
    COHORT_SCHEMA_VERSION,
    CohortError,
    annotation_manifest,
    probe_video,
    replace_output,
    require_tools,
    sha256_file,
    write_json,
)


SOURCE_DATASET = "UP-Fall"
SOURCE_VERSION = "official_rgb_2018"
MATERIALIZER_VERSION = "up_fall_rgb_materializer_v1"
OFFICIAL_PAGE = "https://sites.google.com/up.edu.mx/har-up/"
NOMINAL_FPS = 18.0
EXPECTED_WIDTH = 640
EXPECTED_HEIGHT = 480
MAX_FRAME_BYTES = 10 * 1024 * 1024
FALL_ACTIVITIES = {
    1: "falling_forward_hands",
    2: "falling_forward_knees",
    3: "falling_backward",
    4: "falling_sideward",
    5: "falling_sitting",
}
ADL_ACTIVITIES = {
    8: "sitting",
    9: "picking_up_object",
    11: "laying",
}
ACTIVITIES = {**FALL_ACTIVITIES, **ADL_ACTIVITIES}
INPUT_SPLIT_ROLES = {
    "train_candidate": "train_candidate",
    "validation_candidate": "validation",
}
REQUIRED_SELECTION_COLUMNS = {
    "subject_id",
    "activity_id",
    "activity_name",
    "trial_id",
    "camera_id",
    "drive_file_id",
    "expected_bytes",
    "split_role",
    "download_url",
}
TIMESTAMP_PATTERN = re.compile(
    r"^(\d{4}-\d{2}-\d{2}T\d{2}_\d{2}_\d{2}\.\d{6})\.png$"
)
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", required=True)
    parser.add_argument("--selection-manifest", required=True)
    parser.add_argument("--checksums", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--ffprobe", default="ffprobe")
    parser.add_argument("--fps", type=float, default=NOMINAL_FPS)
    parser.add_argument("--crf", type=int, default=20)
    parser.add_argument("--preset", default="veryfast")
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def _parse_positive_int(value: object, field: str, row_number: int) -> int:
    try:
        parsed = int(str(value))
    except (TypeError, ValueError) as exc:
        raise CohortError(f"selection {row_number}행 {field}가 정수가 아닙니다.") from exc
    if parsed <= 0:
        raise CohortError(f"selection {row_number}행 {field}는 0보다 커야 합니다.")
    return parsed


def _load_checksums(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise CohortError(f"SHA256SUMS 파일이 없습니다: {path}")
    checksums = {}
    with open(path, "r", encoding="utf-8") as file:
        for line_number, raw_line in enumerate(file, start=1):
            line = raw_line.strip()
            if not line:
                continue
            parts = line.split(maxsplit=1)
            if len(parts) != 2 or not SHA256_PATTERN.fullmatch(parts[0]):
                raise CohortError(f"SHA256SUMS {line_number}행 형식이 잘못됐습니다.")
            filename = Path(parts[1].lstrip("*")).name
            if filename in checksums:
                raise CohortError(f"SHA256SUMS 파일명이 중복됩니다: {filename}")
            checksums[filename] = parts[0]
    if not checksums:
        raise CohortError("SHA256SUMS가 비어 있습니다.")
    return checksums


def _archive_filename(row: Mapping[str, object]) -> str:
    return (
        f"Subject{row['subject_id']}Activity{row['activity_id']}"
        f"Trial{row['trial_id']}Camera{row['camera_id']}.zip"
    )


def load_selection(
    source_dir: Path,
    selection_path: Path,
    checksums_path: Path,
) -> list[dict]:
    if not selection_path.is_file():
        raise CohortError(f"selection manifest가 없습니다: {selection_path}")
    checksums = _load_checksums(checksums_path)
    records = []
    seen_archives = set()
    subject_roles: dict[int, set[str]] = defaultdict(set)
    with open(selection_path, "r", encoding="utf-8", newline="") as file:
        reader = csv.DictReader(file, delimiter="\t")
        missing = REQUIRED_SELECTION_COLUMNS - set(reader.fieldnames or [])
        if missing:
            raise CohortError(f"selection 필수 컬럼이 없습니다: {sorted(missing)}")
        for row_number, raw in enumerate(reader, start=2):
            subject_id = _parse_positive_int(raw["subject_id"], "subject_id", row_number)
            activity_id = _parse_positive_int(raw["activity_id"], "activity_id", row_number)
            trial_id = _parse_positive_int(raw["trial_id"], "trial_id", row_number)
            camera_id = _parse_positive_int(raw["camera_id"], "camera_id", row_number)
            expected_bytes = _parse_positive_int(
                raw["expected_bytes"], "expected_bytes", row_number
            )
            activity_name = (raw["activity_name"] or "").strip()
            expected_activity = ACTIVITIES.get(activity_id)
            if expected_activity is None or activity_name != expected_activity:
                raise CohortError(
                    f"selection {row_number}행 activity가 허용 목록과 다릅니다: "
                    f"{activity_id}/{activity_name!r}"
                )
            input_role = (raw["split_role"] or "").strip()
            split_role = INPUT_SPLIT_ROLES.get(input_role)
            if split_role is None:
                raise CohortError(
                    f"selection {row_number}행 split_role이 올바르지 않습니다: "
                    f"{input_role!r}"
                )
            parsed = {
                "subject_id": subject_id,
                "activity_id": activity_id,
                "activity_name": activity_name,
                "trial_id": trial_id,
                "camera_id": camera_id,
            }
            filename = _archive_filename(parsed)
            if filename in seen_archives:
                raise CohortError(f"selection archive가 중복됩니다: {filename}")
            seen_archives.add(filename)
            archive_path = source_dir / filename
            if not archive_path.is_file():
                raise CohortError(f"UP-Fall archive가 없습니다: {archive_path}")
            if archive_path.stat().st_size != expected_bytes:
                raise CohortError(
                    f"UP-Fall archive 크기가 selection과 다릅니다: {filename}"
                )
            expected_sha256 = checksums.get(filename)
            if expected_sha256 is None:
                raise CohortError(f"SHA256SUMS에 archive가 없습니다: {filename}")
            actual_sha256 = sha256_file(archive_path)
            if actual_sha256 != expected_sha256:
                raise CohortError(f"UP-Fall archive SHA-256이 다릅니다: {filename}")
            subject_roles[subject_id].add(split_role)
            records.append(
                {
                    **parsed,
                    "split_role": split_role,
                    "source_archive": filename,
                    "source_archive_path": archive_path,
                    "source_archive_size_bytes": expected_bytes,
                    "source_archive_sha256": actual_sha256,
                    "drive_file_id": (raw["drive_file_id"] or "").strip(),
                }
            )
    if not records:
        raise CohortError("selection manifest가 비어 있습니다.")
    leaking = sorted(subject for subject, roles in subject_roles.items() if len(roles) != 1)
    if leaking:
        raise CohortError(f"Subject가 여러 split에 포함됩니다: {leaking}")
    return sorted(
        records,
        key=lambda item: (
            item["split_role"],
            item["subject_id"],
            item["activity_id"],
            item["trial_id"],
            item["camera_id"],
        ),
    )


def _parse_timestamp(filename: str) -> datetime:
    match = TIMESTAMP_PATTERN.fullmatch(filename)
    if match is None:
        raise CohortError(f"UP-Fall frame 이름 형식이 올바르지 않습니다: {filename}")
    return datetime.strptime(match.group(1), "%Y-%m-%dT%H_%M_%S.%f")


def validate_archive_entries(archive: ZipFile) -> tuple[list[ZipInfo], list[datetime]]:
    entries = []
    seen = set()
    for info in archive.infolist():
        if info.is_dir():
            continue
        pure = PurePosixPath(info.filename)
        if len(pure.parts) != 1 or pure.name != info.filename or "\\" in info.filename:
            raise CohortError(f"UP-Fall ZIP 내부 경로가 안전하지 않습니다: {info.filename}")
        if info.filename in seen:
            raise CohortError(f"UP-Fall ZIP frame 이름이 중복됩니다: {info.filename}")
        if info.flag_bits & 0x1:
            raise CohortError(f"암호화된 UP-Fall frame은 지원하지 않습니다: {info.filename}")
        if info.file_size <= 0 or info.file_size > MAX_FRAME_BYTES:
            raise CohortError(f"UP-Fall frame 크기가 올바르지 않습니다: {info.filename}")
        _parse_timestamp(info.filename)
        seen.add(info.filename)
        entries.append(info)
    if len(entries) < 2:
        raise CohortError("UP-Fall ZIP에는 PNG frame이 2개 이상 필요합니다.")
    entries.sort(key=lambda item: item.filename)
    timestamps = [_parse_timestamp(info.filename) for info in entries]
    if any(left >= right for left, right in zip(timestamps, timestamps[1:])):
        raise CohortError("UP-Fall frame timestamp가 엄격한 오름차순이 아닙니다.")
    return entries, timestamps


def _validate_png_header(header: bytes, filename: str) -> None:
    if len(header) < 24 or header[:8] != PNG_SIGNATURE or header[12:16] != b"IHDR":
        raise CohortError(f"PNG header가 올바르지 않습니다: {filename}")
    width, height = struct.unpack(">II", header[16:24])
    if (width, height) != (EXPECTED_WIDTH, EXPECTED_HEIGHT):
        raise CohortError(
            f"UP-Fall frame 해상도가 {EXPECTED_WIDTH}x{EXPECTED_HEIGHT}가 아닙니다: "
            f"{filename}: {width}x{height}"
        )


def _copy_frame_to_pipe(source: BinaryIO, destination: BinaryIO, info: ZipInfo) -> None:
    header = source.read(24)
    _validate_png_header(header, info.filename)
    destination.write(header)
    while True:
        chunk = source.read(1024 * 1024)
        if not chunk:
            break
        destination.write(chunk)


def transcode_archive(
    archive_path: Path,
    destination: Path,
    ffmpeg: str,
    fps: float,
    crf: int,
    preset: str,
) -> dict:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.stem}.part.mp4")
    command = [
        ffmpeg,
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "image2pipe",
        "-framerate",
        f"{fps:.6f}",
        "-vcodec",
        "png",
        "-i",
        "pipe:0",
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
    process = None
    try:
        with ZipFile(archive_path) as archive:
            entries, timestamps = validate_archive_entries(archive)
            process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
            if process.stdin is None:
                raise CohortError("ffmpeg stdin을 열 수 없습니다.")
            for info in entries:
                with archive.open(info) as source:
                    _copy_frame_to_pipe(source, process.stdin, info)
            process.stdin.close()
            stderr = process.stderr.read() if process.stderr is not None else b""
            return_code = process.wait()
            if return_code != 0:
                raise CohortError(
                    f"ffmpeg 변환 실패: {archive_path.name}: "
                    f"{stderr.decode('utf-8', errors='replace').strip()}"
                )
        temporary.replace(destination)
    except (BadZipFile, OSError, BrokenPipeError) as exc:
        if process is not None and process.poll() is None:
            process.terminate()
            process.wait()
        temporary.unlink(missing_ok=True)
        raise CohortError(f"UP-Fall archive 변환 실패: {archive_path}: {exc}") from exc
    except Exception:
        if process is not None and process.poll() is None:
            process.terminate()
            process.wait()
        temporary.unlink(missing_ok=True)
        raise

    elapsed = (timestamps[-1] - timestamps[0]).total_seconds()
    observed_fps = (len(entries) - 1) / elapsed if elapsed > 0 else 0.0
    if not 10.0 <= observed_fps <= 30.0:
        destination.unlink(missing_ok=True)
        raise CohortError(
            f"UP-Fall timestamp 기반 FPS가 허용 범위를 벗어납니다: {observed_fps:.3f}"
        )
    return {
        "frame_count": len(entries),
        "first_timestamp": timestamps[0].isoformat(timespec="microseconds"),
        "last_timestamp": timestamps[-1].isoformat(timespec="microseconds"),
        "observed_fps": observed_fps,
    }


def _validate_output_probe(probe: Mapping[str, object], frame_count: int, fps: float) -> None:
    if probe.get("codec_name") != "h264":
        raise CohortError(f"UP-Fall 출력 codec이 h264가 아닙니다: {probe.get('codec_name')}")
    if (probe.get("width"), probe.get("height")) != (
        EXPECTED_WIDTH,
        EXPECTED_HEIGHT,
    ):
        raise CohortError("UP-Fall 출력 해상도가 원본과 다릅니다.")
    if probe.get("frame_count") != frame_count:
        raise CohortError("UP-Fall 변환 전후 frame 수가 다릅니다.")
    if not math.isclose(float(probe["fps"]), fps, rel_tol=1e-4, abs_tol=1e-4):
        raise CohortError("UP-Fall 출력 FPS가 요청값과 다릅니다.")


def materialize(
    source_dir: Path,
    selection_path: Path,
    checksums_path: Path,
    output_dir: Path,
    ffmpeg: str,
    ffprobe: str,
    fps: float,
    crf: int,
    preset: str,
    force: bool,
) -> dict:
    if not math.isfinite(fps) or fps <= 0:
        raise CohortError("--fps는 0보다 큰 유한한 값이어야 합니다.")
    if not 0 <= crf <= 51:
        raise CohortError("--crf는 0 이상 51 이하여야 합니다.")
    if output_dir.exists() and not force:
        raise CohortError(f"{output_dir}가 이미 있습니다 (--force로 전체 교체).")
    require_tools(ffmpeg, ffprobe)
    selection = load_selection(source_dir, selection_path, checksums_path)

    output_dir.parent.mkdir(parents=True, exist_ok=True)
    staging_dir = Path(
        tempfile.mkdtemp(prefix=f".{output_dir.name}.build-", dir=output_dir.parent)
    )
    videos = []
    annotation_rows: dict[str, list[dict]] = defaultdict(list)
    try:
        total = len(selection)
        for index, source in enumerate(selection, start=1):
            video_id = (
                f"upfall_s{source['subject_id']:02d}_a{source['activity_id']:02d}_"
                f"t{source['trial_id']:02d}_c{source['camera_id']:02d}"
            )
            relative_path = Path("videos") / source["split_role"] / f"{video_id}.mp4"
            output_path = staging_dir / relative_path
            stream_meta = transcode_archive(
                source["source_archive_path"],
                output_path,
                ffmpeg,
                fps,
                crf,
                preset,
            )
            output_probe = probe_video(output_path, ffprobe)
            _validate_output_probe(output_probe, stream_meta["frame_count"], fps)
            is_fall = source["activity_id"] in FALL_ACTIVITIES
            label = "fall" if is_fall else "no_fall"
            review_status = "needs_review" if is_fall else "reviewed"
            videos.append(
                {
                    "video_id": video_id,
                    "label": label,
                    "activity_name": source["activity_name"],
                    "subject_id": source["subject_id"],
                    "trial_id": source["trial_id"],
                    "camera_id": source["camera_id"],
                    "split_role": source["split_role"],
                    "video_path": relative_path.as_posix(),
                    "source_archive": source["source_archive"],
                    "source_archive_size_bytes": source["source_archive_size_bytes"],
                    "source_archive_sha256": source["source_archive_sha256"],
                    "drive_file_id": source["drive_file_id"],
                    "output_size_bytes": output_path.stat().st_size,
                    "output_sha256": sha256_file(output_path),
                    "output_probe": output_probe,
                    **stream_meta,
                }
            )
            annotation_rows[source["split_role"]].append(
                {
                    "video_id": video_id,
                    "label": label,
                    "video_path": relative_path.as_posix(),
                    "fall_start_frame": "",
                    "impact_frame": "",
                    "lying_start_frame": "",
                    "review_status": review_status,
                    "dataset_fall_label_frame": "",
                }
            )
            print(f"UP-Fall H.264 변환 {index}/{total}: {video_id}")

        annotations = annotation_manifest(staging_dir, annotation_rows)
        split_counts = Counter(video["split_role"] for video in videos)
        split_subjects: dict[str, list[int]] = {}
        for split_role in split_counts:
            split_subjects[split_role] = sorted(
                {video["subject_id"] for video in videos if video["split_role"] == split_role}
            )
        manifest = {
            "schema_version": COHORT_SCHEMA_VERSION,
            "materializer_version": MATERIALIZER_VERSION,
            "source_dataset": SOURCE_DATASET,
            "source_version": SOURCE_VERSION,
            "official_page": OFFICIAL_PAGE,
            "license_status": "official_public_download_no_explicit_license_found",
            "redistribution_allowed": False,
            "selection_manifest_sha256": sha256_file(selection_path),
            "checksums_sha256": sha256_file(checksums_path),
            "split_policy": {
                "unit": "subject",
                "train_candidate_subjects": split_subjects.get("train_candidate", []),
                "validation_subjects": split_subjects.get("validation", []),
            },
            "nominal_fps": fps,
            "encoder": "libx264",
            "pixel_format": "yuv420p",
            "crf": crf,
            "preset": preset,
            "video_count": len(videos),
            "split_counts": dict(sorted(split_counts.items())),
            "annotations": annotations,
            "videos": videos,
        }
        write_json(staging_dir / COHORT_MANIFEST, manifest)
        replace_output(staging_dir, output_dir, force)
        return manifest
    except BaseException:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise


def main() -> None:
    args = parse_args()
    try:
        manifest = materialize(
            Path(args.source_dir),
            Path(args.selection_manifest),
            Path(args.checksums),
            Path(args.output_dir),
            args.ffmpeg,
            args.ffprobe,
            args.fps,
            args.crf,
            args.preset,
            args.force,
        )
    except CohortError as exc:
        raise SystemExit(str(exc)) from exc
    print(
        f"UP-Fall 실제 RGB cohort: {manifest['video_count']} videos -> "
        f"{args.output_dir}"
    )


if __name__ == "__main__":
    main()
