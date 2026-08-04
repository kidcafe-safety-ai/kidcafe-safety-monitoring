r"""OmniFall OF-Synthetic에서 hard-negative challenge cohort를 고른다.

이 단계는 영상을 추출하거나 학습 라벨을 만들지 않는다. 공식 random split의
temporal annotation만 읽어 다음 조건을 만족하는 segment 목록을 만든다.

- 길이가 0인 annotation은 감사 기록에 남기고 제외한다.
- 같은 영상에 ``fall`` 또는 ``fallen`` segment가 하나라도 있으면 제외한다.
- sit/kneel/squat/lie/crawl 계열만 후보로 사용한다.
- 한 행동의 대량 샘플이 cohort를 지배하지 않도록 행동별 상한을 둔다.
- 연령대와 환경 조합을 round-robin해 가능한 범위에서 다양성을 유지한다.

출력 cohort는 학습 데이터 자체가 아니다. Train split 출력은 E0 오분류를
채굴하는 데 사용하고, validation/test split 출력은 E0와 후보 모델을 독립적으로
비교하는 데만 사용한다.

Usage:
    python scripts/select_omnifall_hard_negatives.py \
        --labels /content/phase4_a2/datasets/omnifall/labels/of-syn.csv \
        --split-file \
            /content/phase4_a2/datasets/omnifall/splits/syn/random/train.csv \
        --split-role train \
        --source-manifest \
            /content/drive/MyDrive/kidcafe-data/phase4/source_manifests/\
omnifall_of_syn_source.json \
        --output-dir \
            /content/drive/MyDrive/kidcafe-data/phase4/selection/omnifall_e1
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import tempfile
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


LABEL_NAMES = {
    0: "walk",
    1: "fall",
    2: "fallen",
    3: "sit_down",
    4: "sitting",
    5: "lie_down",
    6: "lying",
    7: "stand_up",
    8: "standing",
    9: "other",
    10: "kneel_down",
    11: "kneeling",
    12: "squat_down",
    13: "squatting",
    14: "crawl",
    15: "jump",
}
TARGET_LABELS = {
    3: "sit_down",
    4: "sitting",
    5: "lie_down",
    6: "lying",
    10: "kneel_down",
    11: "kneeling",
    12: "squat_down",
    13: "squatting",
    14: "crawl",
}
POSITIVE_LABELS = {1, 2}
POSITIVE_PRIMARY_CATEGORIES = {"fall", "fallen"}
REQUIRED_LABEL_COLUMNS = {
    "path",
    "label",
    "start",
    "end",
    "age_group",
    "environment_category",
}
OUTPUT_CSV = "selection.csv"
OUTPUT_JSON = "selection_manifest.json"
SELECTION_SCHEMA_VERSION = "omnifall_hard_negative_selection_v2"
SPLIT_ROLES = ("train", "validation", "test")


class SelectionError(ValueError):
    """입력 데이터나 선별 설정이 계약을 만족하지 않을 때 발생한다."""


@dataclass(frozen=True)
class Segment:
    path: str
    label: int
    activity: str
    start_sec: float
    end_sec: float
    duration_sec: float
    age_group: str
    environment_category: str
    gender_presentation: str
    camera_elevation: str
    camera_distance: str

    @property
    def archive_member(self) -> str:
        return f"{self.path}.mp4"

    @property
    def stratum(self) -> Tuple[str, str]:
        return self.age_group, self.environment_category


@dataclass(frozen=True)
class AuditResult:
    total_label_rows: int
    split_video_count: int
    zero_duration_rows: List[dict]
    positive_video_count: int
    target_segment_count: int
    excluded_positive_target_segment_count: int
    excluded_positive_primary_target_segment_count: int
    eligible_target_segment_count: int
    deduplicated_candidate_count: int
    eligible_by_activity: Dict[str, int]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--labels", required=True, help="OmniFall labels/of-syn.csv")
    parser.add_argument(
        "--split-file",
        "--train-split",
        dest="split_file",
        required=True,
        help=(
            "OmniFall splits/syn/random/{train,validation,test}.csv "
            "(--train-split은 이전 실행 호환 alias)"
        ),
    )
    parser.add_argument("--split-role", choices=SPLIT_ROLES, default="train")
    parser.add_argument(
        "--source-manifest",
        help="다운로드 revision과 archive SHA-256을 기록한 JSON",
    )
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--max-segments-per-activity", type=int, default=100)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_csv(path: Path) -> Tuple[List[dict], List[str]]:
    if not path.is_file():
        raise SelectionError(f"CSV가 없습니다: {path}")
    with open(path, "r", encoding="utf-8", newline="") as file:
        reader = csv.DictReader(file)
        fieldnames = list(reader.fieldnames or [])
        return list(reader), fieldnames


def _required_text(row: Mapping[str, str], field: str, row_number: int) -> str:
    value = (row.get(field) or "").strip()
    if not value:
        raise SelectionError(f"labels:{row_number}의 {field}가 비어 있습니다.")
    return value


def _parse_float(row: Mapping[str, str], field: str, row_number: int) -> float:
    raw = _required_text(row, field, row_number)
    try:
        value = float(raw)
    except ValueError as exc:
        raise SelectionError(
            f"labels:{row_number}의 {field}가 숫자가 아닙니다: {raw!r}"
        ) from exc
    if not math.isfinite(value):
        raise SelectionError(
            f"labels:{row_number}의 {field}가 유한한 값이 아닙니다: {raw!r}"
        )
    return value


def _parse_label(row: Mapping[str, str], row_number: int) -> int:
    raw = _required_text(row, "label", row_number)
    try:
        value = int(raw)
    except ValueError as exc:
        raise SelectionError(
            f"labels:{row_number}의 label이 정수가 아닙니다: {raw!r}"
        ) from exc
    if value not in LABEL_NAMES:
        raise SelectionError(f"labels:{row_number}에 알 수 없는 label={value}가 있습니다.")
    return value


def _optional_text(row: Mapping[str, str], field: str) -> str:
    return (row.get(field) or "unknown").strip() or "unknown"


def _load_split_paths(path: Path) -> List[str]:
    rows, fieldnames = _read_csv(path)
    if "path" not in fieldnames:
        raise SelectionError(f"{path}에 path 컬럼이 없습니다.")
    paths = []
    seen = set()
    for row_number, row in enumerate(rows, start=2):
        value = (row.get("path") or "").strip()
        if not value:
            raise SelectionError(f"{path}:{row_number}의 path가 비어 있습니다.")
        if value in seen:
            raise SelectionError(f"{path}에 path가 중복됩니다: {value}")
        seen.add(value)
        paths.append(value)
    if not paths:
        raise SelectionError(f"{path}에 split 영상이 없습니다.")
    return paths


def audit_candidates(
    labels_path: Path, split_path: Path
) -> Tuple[List[Segment], AuditResult]:
    rows, fieldnames = _read_csv(labels_path)
    missing = REQUIRED_LABEL_COLUMNS - set(fieldnames)
    if missing:
        raise SelectionError(
            f"{labels_path}에 필수 컬럼이 없습니다: {sorted(missing)}"
        )
    split_paths = set(_load_split_paths(split_path))

    parsed_rows = []
    zero_duration_rows = []
    positive_paths = set()
    for row_number, row in enumerate(rows, start=2):
        path = _required_text(row, "path", row_number)
        label = _parse_label(row, row_number)
        start = _parse_float(row, "start", row_number)
        end = _parse_float(row, "end", row_number)
        duration = end - start
        if duration < 0:
            raise SelectionError(
                f"labels:{row_number}의 시간 순서가 역전됐습니다: "
                f"path={path!r}, start={start}, end={end}"
            )
        if path in split_paths and label in POSITIVE_LABELS:
            positive_paths.add(path)
        if duration == 0:
            zero_duration_rows.append(
                {
                    "row_number": row_number,
                    "path": path,
                    "label": label,
                    "start": start,
                    "end": end,
                }
            )
            continue
        parsed_rows.append((row_number, row, path, label, start, end, duration))

    target_segment_count = 0
    excluded_positive_target_segment_count = 0
    excluded_positive_primary_target_segment_count = 0
    eligible_target_segment_count = 0
    best_by_video_activity: Dict[Tuple[str, int], Segment] = {}
    for row_number, row, path, label, start, end, duration in parsed_rows:
        if path not in split_paths or label not in TARGET_LABELS:
            continue
        target_segment_count += 1
        if path in positive_paths:
            excluded_positive_target_segment_count += 1
            continue
        primary_category = path.split("/", 1)[0]
        if primary_category in POSITIVE_PRIMARY_CATEGORIES:
            excluded_positive_primary_target_segment_count += 1
            continue
        eligible_target_segment_count += 1
        segment = Segment(
            path=path,
            label=label,
            activity=TARGET_LABELS[label],
            start_sec=start,
            end_sec=end,
            duration_sec=duration,
            age_group=_required_text(row, "age_group", row_number),
            environment_category=_required_text(
                row, "environment_category", row_number
            ),
            gender_presentation=_optional_text(row, "gender_presentation"),
            camera_elevation=_optional_text(row, "camera_elevation"),
            camera_distance=_optional_text(row, "camera_distance"),
        )
        key = path, label
        current = best_by_video_activity.get(key)
        if current is None or (segment.duration_sec, -segment.start_sec) > (
            current.duration_sec,
            -current.start_sec,
        ):
            best_by_video_activity[key] = segment

    candidates = list(best_by_video_activity.values())
    if not candidates:
        raise SelectionError("선별 가능한 순수 hard-negative segment가 없습니다.")
    counts: Dict[str, int] = defaultdict(int)
    for segment in candidates:
        counts[segment.activity] += 1
    return candidates, AuditResult(
        total_label_rows=len(rows),
        split_video_count=len(split_paths),
        zero_duration_rows=zero_duration_rows,
        positive_video_count=len(positive_paths),
        target_segment_count=target_segment_count,
        excluded_positive_target_segment_count=(
            excluded_positive_target_segment_count
        ),
        excluded_positive_primary_target_segment_count=(
            excluded_positive_primary_target_segment_count
        ),
        eligible_target_segment_count=eligible_target_segment_count,
        deduplicated_candidate_count=len(candidates),
        eligible_by_activity=dict(sorted(counts.items())),
    )


def _stable_key(segment: Segment, seed: int) -> str:
    value = (
        f"{seed}|{segment.activity}|{segment.path}|"
        f"{segment.start_sec:.9f}|{segment.end_sec:.9f}"
    )
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def select_balanced(
    candidates: Iterable[Segment], max_per_activity: int, seed: int
) -> List[Segment]:
    if max_per_activity <= 0:
        raise SelectionError("max-segments-per-activity는 1 이상이어야 합니다.")

    by_activity: Dict[str, List[Segment]] = defaultdict(list)
    for segment in candidates:
        by_activity[segment.activity].append(segment)

    selected = []
    activity_order = [TARGET_LABELS[label] for label in TARGET_LABELS]
    for activity in activity_order:
        activity_segments = by_activity.get(activity, [])
        strata: Dict[Tuple[str, str], List[Segment]] = defaultdict(list)
        for segment in activity_segments:
            strata[segment.stratum].append(segment)
        for segments in strata.values():
            segments.sort(key=lambda item: _stable_key(item, seed))

        stratum_order = sorted(strata)
        activity_selected = []
        while len(activity_selected) < max_per_activity:
            added = False
            for stratum in stratum_order:
                if strata[stratum]:
                    activity_selected.append(strata[stratum].pop(0))
                    added = True
                    if len(activity_selected) == max_per_activity:
                        break
            if not added:
                break
        selected.extend(activity_selected)
    return selected


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


def _csv_text(segments: Sequence[Segment]) -> str:
    import io

    output = io.StringIO(newline="")
    fieldnames = [
        "selection_id",
        "path",
        "archive_member",
        "label",
        "activity",
        "start_sec",
        "end_sec",
        "duration_sec",
        "age_group",
        "environment_category",
        "gender_presentation",
        "camera_elevation",
        "camera_distance",
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    counters: Dict[str, int] = defaultdict(int)
    for segment in segments:
        counters[segment.activity] += 1
        row = asdict(segment)
        row["selection_id"] = (
            f"ofsyn_{segment.activity}_{counters[segment.activity]:04d}"
        )
        row["archive_member"] = segment.archive_member
        writer.writerow({field: row[field] for field in fieldnames})
    return output.getvalue()


def write_selection(
    labels_path: Path,
    split_path: Path,
    split_role: str,
    source_manifest_path: Optional[Path],
    output_dir: Path,
    selected: Sequence[Segment],
    audit: AuditResult,
    max_per_activity: int,
    seed: int,
    force: bool,
) -> None:
    if split_role not in SPLIT_ROLES:
        raise SelectionError(
            f"split_role은 {list(SPLIT_ROLES)} 중 하나여야 합니다: {split_role!r}"
        )
    csv_path = output_dir / OUTPUT_CSV
    json_path = output_dir / OUTPUT_JSON
    existing = [path for path in (csv_path, json_path) if path.exists()]
    if existing and not force:
        raise SelectionError(
            f"출력 파일이 이미 있습니다: {[str(path) for path in existing]} "
            "(--force로 교체 가능)"
        )

    source_manifest = None
    if source_manifest_path is not None:
        if not source_manifest_path.is_file():
            raise SelectionError(f"source manifest가 없습니다: {source_manifest_path}")
        with open(source_manifest_path, "r", encoding="utf-8") as file:
            source_manifest = json.load(file)
        if source_manifest.get("repository") != "simplexsigil2/omnifall":
            raise SelectionError(
                "source manifest repository가 simplexsigil2/omnifall이 아닙니다."
            )
        revision = source_manifest.get("revision")
        archive_sha256 = source_manifest.get("archive_sha256")
        if not isinstance(revision, str) or not revision.strip():
            raise SelectionError("source manifest revision이 비어 있습니다.")
        if (
            not isinstance(archive_sha256, str)
            or len(archive_sha256) != 64
            or any(character not in "0123456789abcdef" for character in archive_sha256)
        ):
            raise SelectionError(
                "source manifest archive_sha256은 소문자 SHA-256이어야 합니다."
            )

    csv_content = _csv_text(selected)
    csv_sha256 = hashlib.sha256(csv_content.encode("utf-8")).hexdigest()
    selected_counts: Dict[str, int] = defaultdict(int)
    for segment in selected:
        selected_counts[segment.activity] += 1
    manifest = {
        "schema_version": SELECTION_SCHEMA_VERSION,
        "source": {
            "labels_path": str(labels_path),
            "labels_sha256": _sha256(labels_path),
            "split_path": str(split_path),
            "split_sha256": _sha256(split_path),
            "download_manifest_path": (
                str(source_manifest_path) if source_manifest_path else None
            ),
            "download_manifest_sha256": (
                _sha256(source_manifest_path) if source_manifest_path else None
            ),
            "repository_revision": (
                source_manifest.get("revision") if source_manifest else None
            ),
            "archive_sha256": (
                source_manifest.get("archive_sha256") if source_manifest else None
            ),
        },
        "policy": {
            "split_family": "of-syn random",
            "split_role": split_role,
            "target_labels": TARGET_LABELS,
            "excluded_video_labels": sorted(POSITIVE_LABELS),
            "excluded_primary_categories": sorted(POSITIVE_PRIMARY_CATEGORIES),
            "exclude_zero_duration": True,
            "deduplicate_by": ["path", "activity"],
            "deduplicate_preference": "longest segment",
            "balance_strata": ["age_group", "environment_category"],
            "max_segments_per_activity": max_per_activity,
            "seed": seed,
            "purpose": {
                "train": "E0 false-positive mining; not direct training input",
                "validation": (
                    "independent E0/E1 model comparison; not training input"
                ),
                "test": "final external evaluation; not training or model selection",
            }[split_role],
        },
        "audit": asdict(audit),
        "selection": {
            "segment_count": len(selected),
            "unique_video_count": len({segment.path for segment in selected}),
            "csv_sha256": csv_sha256,
            "by_activity": dict(sorted(selected_counts.items())),
        },
    }
    _atomic_write_text(csv_path, csv_content)
    _atomic_write_text(
        json_path, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    )


def main() -> None:
    args = parse_args()
    labels_path = Path(args.labels)
    split_path = Path(args.split_file)
    source_manifest_path = (
        Path(args.source_manifest) if args.source_manifest is not None else None
    )
    output_dir = Path(args.output_dir)

    candidates, audit = audit_candidates(labels_path, split_path)
    selected = select_balanced(
        candidates,
        max_per_activity=args.max_segments_per_activity,
        seed=args.seed,
    )
    write_selection(
        labels_path=labels_path,
        split_path=split_path,
        split_role=args.split_role,
        source_manifest_path=source_manifest_path,
        output_dir=output_dir,
        selected=selected,
        audit=audit,
        max_per_activity=args.max_segments_per_activity,
        seed=args.seed,
        force=args.force,
    )
    print(
        f"OmniFall hard-negative cohort: {len(selected)} segments / "
        f"{len({segment.path for segment in selected})} videos -> {output_dir}"
    )


if __name__ == "__main__":
    try:
        main()
    except SelectionError as exc:
        raise SystemExit(str(exc)) from exc
