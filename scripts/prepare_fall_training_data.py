"""CAUCAFall의 프레임별 PNG+YOLO txt 라벨을 Ultralytics 객체 탐지(0=nofall,1=fall)

detection 학습 포맷(images/{split}, labels/{split})으로 변환한다.

CAUCAFall은 활동 폴더(예: `Subject.1/Fall forward`)마다 프레임 PNG와 `{class}
{cx} {cy} {w} {h}` 형식의 YOLO txt 라벨을 이미 제공한다(classes.txt: 0=nofall,
1=fall). 이 스크립트는 별도 변환 없이 이 PNG/txt 쌍을 그대로 학습 디렉터리로
복사만 한다 — 라벨 생성 로직(class 0→1 전환 지점 추정)은
generate_caucafall_annotations.py가 이미 검수까지 마쳤고, 이 스크립트는 그
결과가 아니라 CAUCAFall이 프레임 단위로 원래 제공하는 txt 라벨을 직접 쓴다.

Subject 기준 분할만 허용한다: 프레임을 무작위로 섞어 train/val을 나누면 같은
낙상 시퀀스의 인접 프레임이 양쪽에 걸쳐 사실상 동일한 샘플이 누수된다
(docs/data_sources.md, evaluate_fall.py의 Subject 분할 정책과 동일 이유).

파일명 규칙: CAUCAFall의 원본 파일명(`cfs1-00126.png`, `cams100001.png` 등)은
활동 폴더마다 새로 시작해 subject 내에서도 충돌한다. 출력 파일명은
`S{subject}_{activity_slug}_{원본 파일명}`으로 접두해 유일성을 보장한다.

원본 데이터의 알려진 이름 불일치(Development 60개 영상 전수 확인,
docs/fall_evaluation.md 참고):
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

원본 파일명은 바꾸지 않는다 — 이 스크립트가 이상을 재현 가능하게 처리해야
로컬과 Colab에서 항상 같은 결과가 나온다.

실행마다 `--dest`에 `dataset_manifest.json`을 남긴다: 입력 PNG 수, 정상 매칭
수, copia 복구 경로, 라벨 누락으로 제외한 경로, train/val Subject, split별
클래스 프레임 수.

holdout(Subject 9~10)은 evaluate_fall.py와 동일하게 --allow-holdout 없이는
차단한다.

Usage:
    .venv/bin/python scripts/prepare_fall_training_data.py \
        --source-root data/datasets/caucafall/v5/development \
        --dest outputs/fall_training/dataset_internal \
        --train-subjects 1,2,3,4,5 \
        --val-subjects 6 \
        --missing-label-policy skip
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_HOLDOUT_SUBJECTS = {9, 10}
_COPY_SUFFIX_PATTERN = re.compile(r"\s*-\s*copia\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class _FramePair:
    image_path: Path
    label_path: Path
    subject_num: int
    activity_slug: str
    dest_stem: str
    recovered: bool = False


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


def _activity_slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return slug


def _read_first_class(label_path: Path) -> Optional[str]:
    content = label_path.read_text(encoding="utf-8").strip()
    if not content:
        return None
    return content.splitlines()[0].split()[0]


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


def write_split(
    pairs: List[_FramePair], dest: Path, split_name: str, force: bool
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
    for pair in pairs:
        if pair.dest_stem in dest_stems:
            raise ConfigError(f"출력 파일명이 중복됩니다: {pair.dest_stem}")
        dest_stems.add(pair.dest_stem)

        shutil.copy2(pair.image_path, images_dir / f"{pair.dest_stem}.png")
        shutil.copy2(pair.label_path, labels_dir / f"{pair.dest_stem}.txt")
        first_class = _read_first_class(pair.label_path)
        if first_class == "0":
            class_counts["nofall"] += 1
        elif first_class == "1":
            class_counts["fall"] += 1

    return class_counts


def main() -> None:
    args = parse_args()

    train_subjects = _parse_subject_list(args.train_subjects)
    val_subjects = _parse_subject_list(args.val_subjects)
    guard_holdout(train_subjects, val_subjects, args.allow_holdout)
    guard_overlap(train_subjects, val_subjects)

    source_root = Path(args.source_root)
    dest = Path(args.dest)

    manifest = {
        "source_root": str(source_root),
        "train_subjects": train_subjects,
        "val_subjects": val_subjects,
        "missing_label_policy": args.missing_label_policy,
        "splits": {},
    }
    total_input_images = 0

    for split_name, subjects in (("train", train_subjects), ("val", val_subjects)):
        collected = _CollectionResult()
        for subject_num in subjects:
            partial = collect_frame_pairs(source_root, subject_num, args.missing_label_policy)
            collected.pairs.extend(partial.pairs)
            collected.recovered.extend(partial.recovered)
            collected.skipped_missing_label.extend(partial.skipped_missing_label)
            collected.total_input_images += partial.total_input_images
        total_input_images += collected.total_input_images

        if not collected.pairs:
            raise ConfigError(f"{split_name} 분할에 프레임이 하나도 없습니다: {subjects}")

        class_counts = write_split(collected.pairs, dest, split_name, args.force)

        for png_path, label_path in collected.recovered:
            print(f"  [복구] {png_path.name} -> {label_path.name} (' - copia' 접미사 제거)")
        for png_path in collected.skipped_missing_label:
            print(f"  [제외] {png_path} (라벨 없음, --missing-label-policy=skip)")

        manifest["splits"][split_name] = {
            "subjects": subjects,
            "total_input_images": collected.total_input_images,
            "matched_frames": len(collected.pairs),
            "recovered_copia": [
                {"image": str(png), "label": str(txt)} for png, txt in collected.recovered
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
