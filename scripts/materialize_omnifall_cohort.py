"""선별한 OmniFall OF-Synthetic 영상만 tar에서 안전하게 추출한다.

``select_omnifall_hard_negatives.py``가 만든 selection은 E0 오분류 채굴용
cohort다. 이 스크립트는 selection과 archive checksum을 검증한 뒤 선택 영상만
추출하고, 기존 ``cache_fall_signals.py``가 바로 읽을 수 있는 ``no_fall``
annotation CSV를 생성한다. 이 단계도 학습 프레임이나 pseudo bbox 라벨은
만들지 않는다.

Usage:
    python scripts/materialize_omnifall_cohort.py \
        --archive /content/phase4_a2/datasets/omnifall/\
data_files/omnifall-synthetic_av1.tar \
        --selection-dir \
            /content/drive/MyDrive/kidcafe-data/phase4/selection/omnifall_e1 \
        --output-dir /content/phase4_a2/omnifall_e1_cohort
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import shutil
import tarfile
import tempfile
from collections import defaultdict
from pathlib import Path, PurePosixPath
from typing import Dict, List, Mapping, Sequence


SELECTION_SCHEMA_VERSION = "omnifall_hard_negative_selection_v1"
COHORT_SCHEMA_VERSION = "omnifall_e0_mining_cohort_v1"
SELECTION_CSV = "selection.csv"
SELECTION_JSON = "selection_manifest.json"
ANNOTATIONS_CSV = "annotations.csv"
COHORT_INDEX_CSV = "cohort_index.csv"
COHORT_MANIFEST_JSON = "cohort_manifest.json"
REQUIRED_SELECTION_COLUMNS = {
    "selection_id",
    "path",
    "archive_member",
    "label",
    "activity",
    "start_sec",
    "end_sec",
    "duration_sec",
}


class MaterializationError(ValueError):
    """선별 산출물·archive·출력 상태가 계약을 만족하지 않을 때 발생한다."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--archive", required=True)
    parser.add_argument(
        "--selection-dir",
        required=True,
        help="selection.csv와 selection_manifest.json이 있는 디렉터리",
    )
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as file:
        for chunk in iter(lambda: file.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as file:
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _read_selection(selection_dir: Path) -> tuple[List[dict], dict]:
    csv_path = selection_dir / SELECTION_CSV
    manifest_path = selection_dir / SELECTION_JSON
    if not csv_path.is_file() or not manifest_path.is_file():
        raise MaterializationError(
            f"{selection_dir}에 {SELECTION_CSV}와 {SELECTION_JSON}이 필요합니다."
        )
    with open(manifest_path, "r", encoding="utf-8") as file:
        manifest = json.load(file)
    if manifest.get("schema_version") != SELECTION_SCHEMA_VERSION:
        raise MaterializationError(
            "selection schema_version이 다릅니다: "
            f"{manifest.get('schema_version')!r}"
        )
    expected_csv_sha = manifest.get("selection", {}).get("csv_sha256")
    if not isinstance(expected_csv_sha, str) or expected_csv_sha != _sha256(csv_path):
        raise MaterializationError("selection.csv SHA-256이 manifest와 다릅니다.")

    with open(csv_path, "r", encoding="utf-8", newline="") as file:
        reader = csv.DictReader(file)
        missing = REQUIRED_SELECTION_COLUMNS - set(reader.fieldnames or [])
        if missing:
            raise MaterializationError(
                f"selection.csv에 필수 컬럼이 없습니다: {sorted(missing)}"
            )
        rows = list(reader)
    if not rows:
        raise MaterializationError("selection.csv가 비어 있습니다.")
    expected_segments = manifest.get("selection", {}).get("segment_count")
    if expected_segments != len(rows):
        raise MaterializationError(
            f"selection segment 수가 다릅니다: manifest={expected_segments}, "
            f"csv={len(rows)}"
        )
    return rows, manifest


def _safe_member_name(row: Mapping[str, str], row_number: int) -> str:
    path = (row.get("path") or "").strip()
    member_name = (row.get("archive_member") or "").strip()
    if not path or not member_name:
        raise MaterializationError(
            f"selection.csv:{row_number}의 path/archive_member가 비어 있습니다."
        )
    if "\\" in member_name:
        raise MaterializationError(
            f"selection.csv:{row_number}의 archive_member는 '/'를 써야 합니다."
        )
    pure = PurePosixPath(member_name)
    if pure.is_absolute() or ".." in pure.parts or "." in pure.parts:
        raise MaterializationError(
            f"selection.csv:{row_number}의 archive_member가 안전하지 않습니다: "
            f"{member_name!r}"
        )
    if pure.suffix.lower() != ".mp4" or member_name != f"{path}.mp4":
        raise MaterializationError(
            f"selection.csv:{row_number}의 path와 archive_member가 다릅니다: "
            f"path={path!r}, archive_member={member_name!r}"
        )
    return member_name


def validate_rows(rows: Sequence[dict]) -> Dict[str, List[dict]]:
    by_member: Dict[str, List[dict]] = defaultdict(list)
    selection_ids = set()
    for row_number, row in enumerate(rows, start=2):
        selection_id = (row.get("selection_id") or "").strip()
        if not selection_id:
            raise MaterializationError(
                f"selection.csv:{row_number}의 selection_id가 비어 있습니다."
            )
        if selection_id in selection_ids:
            raise MaterializationError(
                f"selection.csv에 selection_id가 중복됩니다: {selection_id}"
            )
        selection_ids.add(selection_id)
        member_name = _safe_member_name(row, row_number)
        try:
            start = float(row["start_sec"])
            end = float(row["end_sec"])
        except (TypeError, ValueError) as exc:
            raise MaterializationError(
                f"selection.csv:{row_number}의 start/end가 숫자가 아닙니다."
            ) from exc
        if not (0 <= start < end):
            raise MaterializationError(
                f"selection.csv:{row_number}의 구간이 올바르지 않습니다: "
                f"start={start}, end={end}"
            )
        by_member[member_name].append(row)
    return dict(by_member)


def _video_id(member_name: str) -> str:
    stem = str(PurePosixPath(member_name).with_suffix(""))
    value = re.sub(r"[^a-zA-Z0-9]+", "_", stem).strip("_")
    if not value:
        raise MaterializationError(f"video_id를 만들 수 없습니다: {member_name!r}")
    return f"ofsyn_{value}"


def _prepare_output(output_dir: Path, force: bool) -> Path:
    videos_dir = output_dir / "videos"
    known_outputs = [
        output_dir / ANNOTATIONS_CSV,
        output_dir / COHORT_INDEX_CSV,
        output_dir / COHORT_MANIFEST_JSON,
    ]
    has_existing = videos_dir.exists() or any(path.exists() for path in known_outputs)
    if has_existing and not force:
        raise MaterializationError(
            f"{output_dir}에 이전 산출물이 있습니다 (--force로 전체 교체 가능)."
        )
    if force:
        shutil.rmtree(videos_dir, ignore_errors=True)
        for path in known_outputs:
            path.unlink(missing_ok=True)
    videos_dir.mkdir(parents=True, exist_ok=True)
    return videos_dir


def _copy_member(source, destination: Path) -> tuple[int, str]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.part")
    digest = hashlib.sha256()
    size = 0
    try:
        with open(temporary, "wb") as output:
            while True:
                chunk = source.read(8 * 1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)
                digest.update(chunk)
                size += len(chunk)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return size, digest.hexdigest()


def extract_selected(
    archive_path: Path,
    by_member: Mapping[str, List[dict]],
    videos_dir: Path,
) -> List[dict]:
    records = []
    with tarfile.open(archive_path, "r") as archive:
        members = {member.name.lstrip("./"): member for member in archive}
        missing = sorted(set(by_member) - set(members))
        if missing:
            raise MaterializationError(
                f"archive에 선택 영상 {len(missing)}개가 없습니다: {missing[:10]}"
            )
        total = len(by_member)
        for index, member_name in enumerate(sorted(by_member), start=1):
            member = members[member_name]
            if not member.isfile() or member.size <= 0:
                raise MaterializationError(
                    f"archive member가 유효한 일반 파일이 아닙니다: {member_name}"
                )
            source = archive.extractfile(member)
            if source is None:
                raise MaterializationError(
                    f"archive member를 읽을 수 없습니다: {member_name}"
                )
            destination = videos_dir.joinpath(*PurePosixPath(member_name).parts)
            size, sha256 = _copy_member(source, destination)
            if size != member.size:
                raise MaterializationError(
                    f"추출 크기가 다릅니다: {member_name}, "
                    f"archive={member.size}, extracted={size}"
                )
            rows = by_member[member_name]
            records.append(
                {
                    "video_id": _video_id(member_name),
                    "source_path": rows[0]["path"],
                    "video_path": str(
                        PurePosixPath("videos").joinpath(member_name)
                    ),
                    "archive_member": member_name,
                    "activities": sorted({row["activity"] for row in rows}),
                    "selection_ids": sorted(row["selection_id"] for row in rows),
                    "segment_count": len(rows),
                    "size_bytes": size,
                    "sha256": sha256,
                }
            )
            if index % 50 == 0 or index == total:
                print(f"영상 추출 {index}/{total}")
    return records


def _annotations_csv(records: Sequence[dict]) -> str:
    output = io.StringIO(newline="")
    fields = [
        "video_id",
        "label",
        "video_path",
        "fall_start_frame",
        "impact_frame",
        "lying_start_frame",
        "review_status",
    ]
    writer = csv.DictWriter(output, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for record in records:
        writer.writerow(
            {
                "video_id": record["video_id"],
                "label": "no_fall",
                "video_path": record["video_path"],
                "fall_start_frame": "",
                "impact_frame": "",
                "lying_start_frame": "",
                "review_status": "reviewed",
            }
        )
    return output.getvalue()


def _index_csv(records: Sequence[dict]) -> str:
    output = io.StringIO(newline="")
    fields = [
        "video_id",
        "source_path",
        "video_path",
        "archive_member",
        "activities",
        "selection_ids",
        "segment_count",
        "size_bytes",
        "sha256",
    ]
    writer = csv.DictWriter(output, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for record in records:
        row = dict(record)
        row["activities"] = "|".join(record["activities"])
        row["selection_ids"] = "|".join(record["selection_ids"])
        writer.writerow({field: row[field] for field in fields})
    return output.getvalue()


def materialize(
    archive_path: Path, selection_dir: Path, output_dir: Path, force: bool
) -> dict:
    if not archive_path.is_file():
        raise MaterializationError(f"archive가 없습니다: {archive_path}")
    rows, selection_manifest = _read_selection(selection_dir)
    by_member = validate_rows(rows)
    expected_archive_sha = selection_manifest.get("source", {}).get(
        "archive_sha256"
    )
    if not isinstance(expected_archive_sha, str):
        raise MaterializationError("selection manifest에 archive_sha256이 없습니다.")
    actual_archive_sha = _sha256(archive_path)
    if actual_archive_sha != expected_archive_sha:
        raise MaterializationError(
            "OmniFall archive SHA-256이 selection manifest와 다릅니다."
        )

    videos_dir = _prepare_output(output_dir, force)
    records = extract_selected(archive_path, by_member, videos_dir)
    if len({record["video_id"] for record in records}) != len(records):
        raise MaterializationError("생성된 video_id가 중복됩니다.")

    annotations_content = _annotations_csv(records)
    index_content = _index_csv(records)
    manifest = {
        "schema_version": COHORT_SCHEMA_VERSION,
        "archive_path": str(archive_path),
        "archive_sha256": actual_archive_sha,
        "selection_dir": str(selection_dir),
        "selection_csv_sha256": selection_manifest["selection"]["csv_sha256"],
        "selection_manifest_sha256": _sha256(selection_dir / SELECTION_JSON),
        "segment_count": len(rows),
        "video_count": len(records),
        "annotations_sha256": hashlib.sha256(
            annotations_content.encode("utf-8")
        ).hexdigest(),
        "cohort_index_sha256": hashlib.sha256(
            index_content.encode("utf-8")
        ).hexdigest(),
        "videos": records,
    }
    _atomic_write_text(output_dir / ANNOTATIONS_CSV, annotations_content)
    _atomic_write_text(output_dir / COHORT_INDEX_CSV, index_content)
    _atomic_write_text(
        output_dir / COHORT_MANIFEST_JSON,
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
    )
    return manifest


def main() -> None:
    args = parse_args()
    manifest = materialize(
        archive_path=Path(args.archive),
        selection_dir=Path(args.selection_dir),
        output_dir=Path(args.output_dir),
        force=args.force,
    )
    print(
        f"OmniFall E0 mining cohort: {manifest['segment_count']} segments / "
        f"{manifest['video_count']} videos -> {args.output_dir}"
    )


if __name__ == "__main__":
    try:
        main()
    except MaterializationError as exc:
        raise SystemExit(str(exc)) from exc
