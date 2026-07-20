r"""CAUCAFall의 프레임별 PNG+YOLO txt 라벨을 Ultralytics 객체 탐지(0=nofall,1=fall)

detection 학습 포맷(images/{split}, labels/{split})으로 변환한다.

CAUCAFall은 활동 폴더(예: `Subject.1/Fall forward`)마다 프레임 PNG와 `{class}
{cx} {cy} {w} {h}` 형식의 YOLO txt 라벨을 이미 제공한다(classes.txt: 0=nofall,
1=fall). 이 스크립트는 별도 변환 없이 이 PNG/txt 쌍을 그대로 학습 디렉터리로
복사하거나 hardlink한다 — 라벨 생성 로직(class 0→1 전환 지점 추정)은
generate_caucafall_annotations.py가 이미 검수까지 마쳤고, 이 스크립트는 그
결과가 아니라 CAUCAFall이 프레임 단위로 원래 제공하는 txt 라벨을 직접 쓴다.

Subject 기준 분할만 허용한다: 프레임을 무작위로 섞어 train/val을 나누면 같은
낙상 시퀀스의 인접 프레임이 양쪽에 걸쳐 사실상 동일한 샘플이 누수된다
(docs/data_sources.md, evaluate_fall.py의 Subject 분할 정책과 동일 이유).

파일명 규칙: CAUCAFall의 원본 파일명(`cfs1-00126.png`, `cams100001.png` 등)은
활동 폴더마다 새로 시작해 subject 내에서도 충돌한다. 출력 파일명은
`S{subject}_{activity_slug}_{원본 파일명}`으로 접두해 유일성을 보장한다.

원본 데이터의 알려진 이름 불일치(Development 60개 영상 전수 확인,
Validation hard-negative 폴더 확인, docs/fall_evaluation.md 참고):
    - `Subject.2/Fall backwards/cas200091 - copia.png`: 대응 라벨은
      `cas200091.txt`(" - copia" 접미사 없음)로 존재한다. 정확한 stem 매칭이
      실패하면 " - copia" 접미사를 제거한 stem으로 같은 폴더에서 라벨을 다시
      찾는다. 숫자만 일치하는 매칭은 절대 하지 않는다(잘못된 라벨을 연결할
      위험) — 접미사 제거 후 정확히 일치하는 후보가 정확히 1개일 때만
      복구한다.
    - `Subject.5/Kneel/ars500236.png`, `Subject.6/Walk/cams600260.png`: 라벨이
      실제로 존재하지 않는다(추정 생성 없음). --missing-label-policy=error
      (기본값)면 즉시 실패하고, =skip이면 해당 프레임만 제외하고 진행한다.
      기본값을 error로 둔 이유는 라벨 누락을 조용히 넘기지 않기 위함이며,
      실제 CAUCAFall 준비 명령에서만 의도적으로 skip을 지정한다.
    - `validation/Subject.8/Pick up object/res800090.png`: 라벨 파일명이
      `res800090a.txt`로 제공된다. 이 정확한 경로 조합만 명시적 1:1 override로
      연결하고, 일반적인 접미사 추측은 하지 않는다.

원본 파일명은 바꾸지 않는다 — 이 스크립트가 이상을 재현 가능하게 처리해야
로컬과 Colab에서 항상 같은 결과가 나온다.

실행마다 `--dest`에 `dataset_manifest.json`을 남긴다: 입력 PNG 수, 정상 매칭
수, copia 복구 경로, 라벨 누락으로 제외한 경로, train/val Subject, split별
클래스 프레임 수.

holdout(Subject 9~10)은 evaluate_fall.py와 동일하게 --allow-holdout 없이는
차단한다.

선택적으로 `--hard-negative-*` 세 옵션을 함께 지정하면 CSV manifest에 적힌
정상행동 폴더만 train에 추가한다. 해당 폴더의 모든 객체 라벨이 class 0인지
전수 검증하며, base train/val Subject와 겹치거나 Subject 9~10을 가리키면
차단한다. Internal val에는 hard-negative 프레임을 추가하지 않는다.

Usage:
    .venv/bin/python scripts/prepare_fall_training_data.py \
        --source-root data/datasets/caucafall/v5/development \
        --dest outputs/fall_training/dataset_internal \
        --train-subjects 1,2,3,4,5 \
        --val-subjects 6 \
        --missing-label-policy skip

    # 디스크 사용량을 줄인 hard-negative Fold A 생성(같은 파일시스템 전제)
    .venv/bin/python scripts/prepare_fall_training_data.py \
        --source-root data/datasets/caucafall/v5/development \
        --dest outputs/fall_training/dataset_hn_fold_a \
        --train-subjects 1,2,3,4,5 \
        --val-subjects 6 \
        --missing-label-policy skip \
        --hard-negative-source-root data/datasets/caucafall/v5/validation \
        --hard-negative-manifest \
            data/annotations/caucafall_v5/hard_negatives_s7.csv \
        --hard-negative-subjects 7 \
        --materialization hardlink
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Dict, List, Optional, Tuple

_HOLDOUT_SUBJECTS = {9, 10}
_COPY_SUFFIX_PATTERN = re.compile(r"\s*-\s*copia\s*$", re.IGNORECASE)
_KNOWN_LABEL_NAME_MISMATCHES = {
    ("Subject.8", "Pick up object", "res800090.png"): "res800090a.txt",
}


@dataclass(frozen=True)
class _FramePair:
    image_path: Path
    label_path: Path
    subject_num: int
    activity_slug: str
    dest_stem: str
    recovered: bool = False


@dataclass(frozen=True)
class _HardNegativeSpec:
    video_id: str
    subject: int
    activity: str
    relative_dir: str
    expected_class: str
    reason: str


@dataclass
class _CollectionResult:
    pairs: List[_FramePair] = field(default_factory=list)
    recovered: List[Tuple[Path, Path]] = field(default_factory=list)
    skipped_missing_label: List[Path] = field(default_factory=list)
    total_input_images: int = 0


class ConfigError(ValueError):
    """CLI 인자·데이터 구성 오류 (사용자가 고쳐야 하는 문제)."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--source-root",
        required=True,
        help="Subject.N 디렉터리를 담은 루트 (예: data/datasets/caucafall/v5/development)",
    )
    parser.add_argument("--dest", required=True, help="출력 데이터셋 루트")
    parser.add_argument(
        "--train-subjects", required=True, help="쉼표로 구분한 Subject 번호 목록 (예: 1,2,3,4,5)"
    )
    parser.add_argument(
        "--val-subjects", required=True, help="쉼표로 구분한 Subject 번호 목록 (예: 6)"
    )
    parser.add_argument(
        "--missing-label-policy",
        default="error",
        choices=["error", "skip"],
        help=(
            "라벨이 실제로 없는 PNG를 만나면: error(기본값)는 즉시 실패, "
            "skip은 해당 프레임을 제외하고 진행 (dataset_manifest.json에 기록됨)."
        ),
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="--dest가 이미 존재해도 내용을 덮어쓴다.",
    )
    parser.add_argument(
        "--allow-holdout",
        action="store_true",
        help="Subject 9~10(holdout)을 --train-subjects/--val-subjects에 포함할 때만 명시적으로 허용한다.",
    )
    parser.add_argument(
        "--hard-negative-source-root",
        help="hard-negative manifest의 relative_dir 기준 루트",
    )
    parser.add_argument(
        "--hard-negative-manifest",
        help="train에만 추가할 nofall 활동 디렉터리 CSV manifest",
    )
    parser.add_argument(
        "--hard-negative-subjects",
        help="manifest에 허용할 Subject 번호 목록(예: Fold A는 7, Fold B는 8)",
    )
    parser.add_argument(
        "--materialization",
        default="copy",
        choices=["copy", "hardlink"],
        help=(
            "출력 데이터 파일 생성 방식. copy(기본값)는 독립 복사하고, "
            "hardlink는 같은 파일시스템에서 추가 디스크 사용량을 줄인다."
        ),
    )
    return parser.parse_args()


def _parse_subject_list(raw: str) -> List[int]:
    try:
        subjects = [int(part.strip()) for part in raw.split(",") if part.strip()]
    except ValueError as exc:
        raise ConfigError(f"Subject 번호 목록이 올바르지 않습니다: {raw!r}") from exc
    if not subjects:
        raise ConfigError(f"Subject 번호 목록이 비어 있습니다: {raw!r}")
    return subjects


def guard_holdout(train_subjects: List[int], val_subjects: List[int], allow_holdout: bool) -> None:
    used = set(train_subjects) | set(val_subjects)
    hit = used & _HOLDOUT_SUBJECTS
    if hit and not allow_holdout:
        raise ConfigError(
            f"Subject {sorted(hit)}는 holdout입니다. 최종 평가 전까지 사용할 수 "
            "없습니다 (--allow-holdout으로 명시적으로 우회 가능)."
        )


def guard_overlap(train_subjects: List[int], val_subjects: List[int]) -> None:
    overlap = set(train_subjects) & set(val_subjects)
    if overlap:
        raise ConfigError(
            f"Subject {sorted(overlap)}가 train/val 양쪽에 모두 포함되어 있습니다 — "
            "같은 사람의 프레임이 양쪽에 섞이면 데이터 누수가 됩니다."
        )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_hard_negative_manifest(path: Path) -> List[_HardNegativeSpec]:
    required = {
        "video_id",
        "subject",
        "activity",
        "relative_dir",
        "expected_class",
        "reason",
    }
    if not path.is_file():
        raise ConfigError(f"hard-negative manifest가 없습니다: {path}")

    with open(path, "r", encoding="utf-8", newline="") as file:
        reader = csv.DictReader(file)
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ConfigError(
                f"{path}에 hard-negative 필수 컬럼이 없습니다: {sorted(missing)}"
            )
        rows = list(reader)

    if not rows:
        raise ConfigError(f"{path}에 hard-negative 항목이 없습니다.")

    specs: List[_HardNegativeSpec] = []
    video_ids = set()
    relative_dirs = set()
    for row_number, row in enumerate(rows, start=2):
        values = {key: (row.get(key) or "").strip() for key in required}
        empty = sorted(key for key, value in values.items() if not value)
        if empty:
            raise ConfigError(f"{path}:{row_number}에 빈 필드가 있습니다: {empty}")
        try:
            subject = int(values["subject"])
        except ValueError as exc:
            raise ConfigError(
                f"{path}:{row_number}의 subject가 정수가 아닙니다: "
                f"{values['subject']!r}"
            ) from exc

        if "\\" in values["relative_dir"]:
            raise ConfigError(
                f"{path}:{row_number}의 relative_dir은 POSIX '/' 구분자를 써야 합니다."
            )
        relative = PurePosixPath(values["relative_dir"])
        if relative.is_absolute() or ".." in relative.parts or "." in relative.parts:
            raise ConfigError(
                f"{path}:{row_number}의 relative_dir은 안전한 상대경로여야 합니다: "
                f"{values['relative_dir']!r}"
            )
        expected_parts = (f"Subject.{subject}", values["activity"])
        if relative.parts != expected_parts:
            raise ConfigError(
                f"{path}:{row_number}의 relative_dir은 "
                f"{'/'.join(expected_parts)!r}이어야 합니다."
            )
        if values["activity"].lower().startswith("fall"):
            raise ConfigError(
                f"{path}:{row_number}에 fall 활동을 hard-negative로 넣을 수 없습니다."
            )
        if values["expected_class"] != "nofall":
            raise ConfigError(
                f"{path}:{row_number}의 expected_class는 nofall이어야 합니다."
            )
        if values["video_id"] in video_ids:
            raise ConfigError(f"{path}에 video_id가 중복됩니다: {values['video_id']}")
        if values["relative_dir"] in relative_dirs:
            raise ConfigError(
                f"{path}에 relative_dir이 중복됩니다: {values['relative_dir']}"
            )
        expected_video_id = f"S{subject}_{_activity_slug(values['activity'])}"
        if values["video_id"] != expected_video_id:
            raise ConfigError(
                f"{path}:{row_number}의 video_id는 {expected_video_id!r}이어야 합니다."
            )
        video_ids.add(values["video_id"])
        relative_dirs.add(values["relative_dir"])
        specs.append(
            _HardNegativeSpec(
                video_id=values["video_id"],
                subject=subject,
                activity=values["activity"],
                relative_dir=values["relative_dir"],
                expected_class=values["expected_class"],
                reason=values["reason"],
            )
        )
    return specs


def _validate_hard_negative_options(args: argparse.Namespace) -> bool:
    values = (
        args.hard_negative_source_root,
        args.hard_negative_manifest,
        args.hard_negative_subjects,
    )
    if any(values) and not all(values):
        raise ConfigError(
            "--hard-negative-source-root, --hard-negative-manifest, "
            "--hard-negative-subjects는 함께 지정해야 합니다."
        )
    return all(values)


def _activity_slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return slug


def _read_first_class(label_path: Path) -> Optional[str]:
    content = label_path.read_text(encoding="utf-8").strip()
    if not content:
        return None
    return content.splitlines()[0].split()[0]


def _read_classes(label_path: Path) -> List[str]:
    classes = []
    for line_number, line in enumerate(
        label_path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        parts = line.split()
        if not parts:
            continue
        if len(parts) != 5:
            raise ConfigError(
                f"{label_path}:{line_number}의 YOLO 라벨은 5개 값이어야 합니다."
            )
        classes.append(parts[0])
    return classes


def _normalize_stem(stem: str) -> str:
    return _COPY_SUFFIX_PATTERN.sub("", stem).strip()


def _find_label_for_image(png_path: Path) -> Tuple[Optional[Path], bool]:
    """정확한 stem 매칭을 우선 시도하고, 실패하면 알려진 접미사(" - copia")만

    제거해 재시도한다. 숫자만 일치하는 매칭은 하지 않는다 — 잘못된 라벨을
    연결할 위험이 있기 때문이다. 접미사 제거 후 후보가 0개 또는 2개 이상이면
    즉시 오류를 낸다(모호한 복구를 허용하지 않음).

    Returns:
        (label_path 또는 None, recovered: 접미사 제거로 복구했는지 여부)
    """
    exact = png_path.with_suffix(".txt")
    if exact.is_file():
        return exact, False

    known_name = _KNOWN_LABEL_NAME_MISMATCHES.get(tuple(png_path.parts[-3:]))
    if known_name is not None:
        known_path = png_path.parent / known_name
        if not known_path.is_file():
            raise ConfigError(
                f"{png_path}의 알려진 override 라벨이 없습니다: {known_path}"
            )
        return known_path, True

    normalized = _normalize_stem(png_path.stem)
    if normalized == png_path.stem:
        return None, False

    candidates = [
        txt
        for txt in png_path.parent.glob("*.txt")
        if txt.name != "classes.txt" and _normalize_stem(txt.stem) == normalized
    ]
    if len(candidates) == 1:
        return candidates[0], True
    if len(candidates) > 1:
        raise ConfigError(
            f"{png_path}의 라벨 복구 후보가 여러 개입니다(모호함): "
            f"{[str(c) for c in candidates]}"
        )
    return None, False


def _recovery_kind(png_path: Path, label_path: Path) -> str:
    if _normalize_stem(png_path.stem) == _normalize_stem(label_path.stem):
        return "copia_suffix"
    return "known_label_name_mismatch"


def collect_frame_pairs(
    source_root: Path, subject_num: int, missing_label_policy: str = "error"
) -> _CollectionResult:
    """Subject.N 아래 모든 활동 폴더에서 PNG+txt 쌍을 수집한다."""
    subject_dir = source_root / f"Subject.{subject_num}"
    if not subject_dir.is_dir():
        raise ConfigError(f"{subject_dir}가 없습니다.")

    result = _CollectionResult()
    for activity_dir in sorted(p for p in subject_dir.iterdir() if p.is_dir()):
        slug = _activity_slug(activity_dir.name)
        png_files = sorted(activity_dir.glob("*.png"))
        used_labels: Dict[Path, Path] = {}
        for png_path in png_files:
            result.total_input_images += 1
            label_path, recovered = _find_label_for_image(png_path)

            if label_path is None:
                if missing_label_policy == "skip":
                    result.skipped_missing_label.append(png_path)
                    continue
                raise ConfigError(
                    f"{png_path}에 대응하는 라벨 파일이 없습니다 "
                    "(--missing-label-policy skip으로 이 프레임만 제외 가능)."
                )

            if label_path in used_labels:
                raise ConfigError(
                    f"라벨 {label_path}가 두 이미지에 연결됩니다: "
                    f"{used_labels[label_path]}, {png_path} — 정상 파일과 ' - copia' "
                    "파일이 동시에 존재해 같은 라벨을 공유할 가능성이 있습니다."
                )
            used_labels[label_path] = png_path

            if recovered:
                result.recovered.append((png_path, label_path))

            dest_stem = f"S{subject_num}_{slug}_{png_path.stem}"
            result.pairs.append(
                _FramePair(
                    image_path=png_path,
                    label_path=label_path,
                    subject_num=subject_num,
                    activity_slug=slug,
                    dest_stem=dest_stem,
                    recovered=recovered,
                )
            )
    return result


def collect_hard_negative_pairs(
    source_root: Path, specs: List[_HardNegativeSpec]
) -> _CollectionResult:
    """Manifest에 명시된 정상행동 폴더만 nofall 학습 보강으로 수집한다."""
    if not source_root.is_dir():
        raise ConfigError(f"hard-negative source root가 없습니다: {source_root}")

    resolved_root = source_root.resolve()
    result = _CollectionResult()
    for spec in specs:
        relative = PurePosixPath(spec.relative_dir)
        activity_dir = source_root.joinpath(*relative.parts)
        if not activity_dir.is_dir():
            raise ConfigError(
                f"hard-negative 활동 디렉터리가 없습니다: {activity_dir}"
            )
        try:
            activity_dir.resolve().relative_to(resolved_root)
        except ValueError as exc:
            raise ConfigError(
                f"hard-negative 활동 디렉터리가 source root 밖을 가리킵니다: "
                f"{activity_dir}"
            ) from exc

        png_files = sorted(activity_dir.glob("*.png"))
        if not png_files:
            raise ConfigError(f"hard-negative PNG가 없습니다: {activity_dir}")

        used_labels: Dict[Path, Path] = {}
        activity_slug = _activity_slug(spec.activity)
        for png_path in png_files:
            result.total_input_images += 1
            try:
                png_path.resolve().relative_to(resolved_root)
            except ValueError as exc:
                raise ConfigError(
                    f"hard-negative 이미지가 source root 밖을 가리킵니다: {png_path}"
                ) from exc
            label_path, recovered = _find_label_for_image(png_path)
            if label_path is None:
                raise ConfigError(
                    f"hard-negative {png_path}에 대응하는 라벨 파일이 없습니다."
                )
            try:
                label_path.resolve().relative_to(resolved_root)
            except ValueError as exc:
                raise ConfigError(
                    f"hard-negative 라벨이 source root 밖을 가리킵니다: {label_path}"
                ) from exc
            if label_path in used_labels:
                raise ConfigError(
                    f"hard-negative 라벨 {label_path}가 두 이미지에 연결됩니다: "
                    f"{used_labels[label_path]}, {png_path}"
                )
            used_labels[label_path] = png_path

            classes = _read_classes(label_path)
            if not classes:
                raise ConfigError(f"hard-negative 라벨이 비어 있습니다: {label_path}")
            if set(classes) != {"0"}:
                raise ConfigError(
                    f"hard-negative 라벨은 class 0(nofall)만 허용합니다: "
                    f"{label_path} classes={sorted(set(classes))}"
                )

            if recovered:
                result.recovered.append((png_path, label_path))
            result.pairs.append(
                _FramePair(
                    image_path=png_path,
                    label_path=label_path,
                    subject_num=spec.subject,
                    activity_slug=activity_slug,
                    dest_stem=f"S{spec.subject}_{activity_slug}_{png_path.stem}",
                    recovered=recovered,
                )
            )
    return result


def _materialize_file(source: Path, destination: Path, mode: str) -> None:
    if mode == "copy":
        shutil.copy2(source, destination)
        return
    try:
        os.link(source, destination)
    except OSError as exc:
        raise ConfigError(
            f"hardlink 생성에 실패했습니다: {source} -> {destination}. "
            "두 경로가 같은 파일시스템인지 확인하거나 --materialization copy를 "
            "사용하세요."
        ) from exc


def write_split(
    pairs: List[_FramePair],
    dest: Path,
    split_name: str,
    force: bool,
    materialization: str = "copy",
) -> Dict[str, int]:
    images_dir = dest / "images" / split_name
    labels_dir = dest / "labels" / split_name

    for d in (images_dir, labels_dir):
        if d.exists():
            existing = list(d.iterdir())
            if existing and not force:
                raise ConfigError(
                    f"{d}가 이미 존재하고 비어 있지 않습니다 (--force로 덮어쓰기 허용)."
                )
            if existing and force:
                # 이전 실행의 잔여 파일을 먼저 지운다 — 그렇지 않으면 이번 실행에서
                # 프레임 수가 줄었을 때 예전 이미지/라벨이 섞여 학습 데이터가
                # 오염된다.
                shutil.rmtree(d)
        d.mkdir(parents=True, exist_ok=True)

    class_counts = {"nofall": 0, "fall": 0}
    dest_stems = set()
    total_pairs = len(pairs)
    for index, pair in enumerate(pairs, start=1):
        if pair.dest_stem in dest_stems:
            raise ConfigError(f"출력 파일명이 중복됩니다: {pair.dest_stem}")
        dest_stems.add(pair.dest_stem)

        _materialize_file(
            pair.image_path,
            images_dir / f"{pair.dest_stem}.png",
            materialization,
        )
        _materialize_file(
            pair.label_path,
            labels_dir / f"{pair.dest_stem}.txt",
            materialization,
        )
        first_class = _read_first_class(pair.label_path)
        if first_class == "0":
            class_counts["nofall"] += 1
        elif first_class == "1":
            class_counts["fall"] += 1
        if index % 500 == 0 or index == total_pairs:
            percent = (index / total_pairs * 100.0) if total_pairs else 100.0
            print(
                f"  [{split_name}] 파일 생성 {index}/{total_pairs} "
                f"({percent:.1f}%)"
            )

    return class_counts


def main() -> None:
    args = parse_args()

    train_subjects = _parse_subject_list(args.train_subjects)
    val_subjects = _parse_subject_list(args.val_subjects)
    guard_holdout(train_subjects, val_subjects, args.allow_holdout)
    guard_overlap(train_subjects, val_subjects)

    source_root = Path(args.source_root)
    dest = Path(args.dest)
    hard_negative_enabled = _validate_hard_negative_options(args)
    hard_negative_specs: List[_HardNegativeSpec] = []
    hard_negative_subjects: List[int] = []
    hard_negative_source_root: Optional[Path] = None
    hard_negative_manifest_path: Optional[Path] = None
    if hard_negative_enabled:
        hard_negative_subjects = _parse_subject_list(args.hard_negative_subjects)
        if len(hard_negative_subjects) != len(set(hard_negative_subjects)):
            raise ConfigError("--hard-negative-subjects에 중복 Subject가 있습니다.")
        guard_holdout(hard_negative_subjects, [], args.allow_holdout)
        overlap = set(hard_negative_subjects) & (set(train_subjects) | set(val_subjects))
        if overlap:
            raise ConfigError(
                f"hard-negative Subject {sorted(overlap)}가 base train/val과 겹칩니다."
            )

        hard_negative_source_root = Path(args.hard_negative_source_root)
        hard_negative_manifest_path = Path(args.hard_negative_manifest)
        hard_negative_specs = load_hard_negative_manifest(hard_negative_manifest_path)
        manifest_subjects = {spec.subject for spec in hard_negative_specs}
        if manifest_subjects != set(hard_negative_subjects):
            raise ConfigError(
                "--hard-negative-subjects와 manifest Subject가 일치하지 않습니다: "
                f"declared={sorted(hard_negative_subjects)}, "
                f"manifest={sorted(manifest_subjects)}"
            )

    manifest = {
        "source_root": str(source_root),
        "train_subjects": train_subjects,
        "val_subjects": val_subjects,
        "missing_label_policy": args.missing_label_policy,
        "materialization": args.materialization,
        "hard_negative": {"enabled": False},
        "splits": {},
    }
    total_input_images = 0

    hard_negative_result = _CollectionResult()
    if hard_negative_enabled:
        hard_negative_result = collect_hard_negative_pairs(
            hard_negative_source_root, hard_negative_specs
        )
        manifest["hard_negative"] = {
            "enabled": True,
            "source_root": str(hard_negative_source_root),
            "manifest_path": str(hard_negative_manifest_path),
            "manifest_sha256": _sha256(hard_negative_manifest_path),
            "subjects": hard_negative_subjects,
            "video_ids": [spec.video_id for spec in hard_negative_specs],
            "activities": [spec.activity for spec in hard_negative_specs],
            "reasons": {spec.video_id: spec.reason for spec in hard_negative_specs},
            "total_input_images": hard_negative_result.total_input_images,
            "matched_frames": len(hard_negative_result.pairs),
            "class_counts": {
                "nofall": len(hard_negative_result.pairs),
                "fall": 0,
            },
        }

    for split_name, subjects in (("train", train_subjects), ("val", val_subjects)):
        collected = _CollectionResult()
        for subject_num in subjects:
            partial = collect_frame_pairs(source_root, subject_num, args.missing_label_policy)
            collected.pairs.extend(partial.pairs)
            collected.recovered.extend(partial.recovered)
            collected.skipped_missing_label.extend(partial.skipped_missing_label)
            collected.total_input_images += partial.total_input_images
        base_matched_frames = len(collected.pairs)
        if split_name == "train" and hard_negative_enabled:
            collected.pairs.extend(hard_negative_result.pairs)
            collected.recovered.extend(hard_negative_result.recovered)
            collected.total_input_images += hard_negative_result.total_input_images
        total_input_images += collected.total_input_images

        if not collected.pairs:
            raise ConfigError(f"{split_name} 분할에 프레임이 하나도 없습니다: {subjects}")

        class_counts = write_split(
            collected.pairs,
            dest,
            split_name,
            args.force,
            materialization=args.materialization,
        )

        for png_path, label_path in collected.recovered:
            recovery_kind = _recovery_kind(png_path, label_path)
            print(
                f"  [복구] {png_path.name} -> {label_path.name} "
                f"({recovery_kind})"
            )
        for png_path in collected.skipped_missing_label:
            print(f"  [제외] {png_path} (라벨 없음, --missing-label-policy=skip)")

        manifest["splits"][split_name] = {
            "subjects": subjects,
            "total_input_images": collected.total_input_images,
            "matched_frames": len(collected.pairs),
            "base_matched_frames": base_matched_frames,
            "hard_negative_matched_frames": (
                len(hard_negative_result.pairs) if split_name == "train" else 0
            ),
            "recovered_copia": [
                {"image": str(png), "label": str(txt)}
                for png, txt in collected.recovered
                if _recovery_kind(png, txt) == "copia_suffix"
            ],
            "recovered_label_mismatches": [
                {
                    "image": str(png),
                    "label": str(txt),
                    "kind": _recovery_kind(png, txt),
                }
                for png, txt in collected.recovered
            ],
            "skipped_missing_label": [str(p) for p in collected.skipped_missing_label],
            "class_counts": class_counts,
        }
        print(
            f"[{split_name}] Subject {subjects}: {len(collected.pairs)}프레임 "
            f"(nofall={class_counts['nofall']}, fall={class_counts['fall']}) -> {dest}"
        )

    manifest["total_input_images"] = total_input_images
    dest.mkdir(parents=True, exist_ok=True)
    manifest_path = dest / "dataset_manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as file:
        json.dump(manifest, file, ensure_ascii=False, indent=2)
    print(f"dataset manifest 저장: {manifest_path}")


if __name__ == "__main__":
    try:
        main()
    except ConfigError as exc:
        raise SystemExit(str(exc)) from exc
