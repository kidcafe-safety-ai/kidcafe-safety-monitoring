"""CAUCAFall V5의 기존 프레임별 YOLO 라벨(class 0/1)에서 evaluate_fall.py용

annotation CSV 초안을 자동 생성한다.

CAUCAFall은 각 프레임마다 `{class} {cx} {cy} {w} {h}` 형식의 txt 라벨을 제공하고,
`classes.txt`가 `0=nofall, 1=fall`을 정의한다 (docs/data_sources.md). 이 스크립트는
활동 폴더 하나(=AVI 한 개)마다 class가 0에서 1로 바뀌는 지점을 찾아 fall_start_frame
후보로 기록한다. 어디까지나 초안이며, `review_status=pending`으로 생성되므로
사람이 실제 영상과 프레임 매핑이 맞는지 검수해야 `reviewed`가 된다.

주의:
    - txt 파일명의 숫자는 subject_id*100000 + 순번 형식이라 그대로 프레임 번호로
      쓸 수 없다. 반드시 파일명 정렬 순서(0-base)를 프레임 번호로 사용한다.
    - CAUCAFall의 txt 개수는 실제 AVI 디코딩 프레임 수보다 1개 많은 경우가
      일관되게 관찰된다. 초과분은 뒤에서부터 제외하고 경고를 남긴다. 이 가정이
      맞는지는 review_caucafall_annotations.py의 사람 검수로 확인해야 한다.

Usage:
    .venv/bin/python scripts/generate_caucafall_annotations.py \
        --dataset-dir data/datasets/caucafall/v5 \
        --output-dir data/annotations/caucafall_v5
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

import cv2

_REQUIRED_COLUMNS = [
    "video_id",
    "label",
    "video_path",
    "fall_start_frame",
    "impact_frame",
    "lying_start_frame",
    "review_status",
]

# Subject 9~10(holdout)은 이 스크립트에서 절대 다루지 않는다 (docs/data_sources.md).
_DEFAULT_SPLIT_CONFIG_PATH = "configs/caucafall_v5_split.json"
_HOLDOUT_SUBJECTS = {9, 10}


def load_split_subjects(path: str) -> Dict[str, List[int]]:
    """configs/caucafall_v5_split.json에서 development/validation Subject 번호를 읽는다.

    이 파일이 docs/data_sources.md Subject 분할의 단일 기준이므로, 이 스크립트가
    자체적으로 범위를 하드코딩하면 두 값이 갈라져도 알아챌 방법이 없다. holdout은
    이 파일에 있어도 이 스크립트에서는 절대 쓰지 않는다 — 아래서 development/
    validation만 읽는다.

    기본 설정 파일(configs/caucafall_v5_split.json)뿐 아니라 --split-config로
    임의의 파일을 지정할 수 있으므로, 커스텀 설정도 다음을 위반하면 조용히
    넘어가지 않고 즉시 실패시킨다: Subject 9~10(holdout) 포함, development/
    validation 중복, 정수가 아닌 Subject 번호.
    """
    with open(path, "r", encoding="utf-8") as file:
        raw = json.load(file)
    required = {"development", "validation"}
    missing = required - set(raw)
    if missing:
        raise ValueError(f"{path}에 필수 분할이 없습니다: {sorted(missing)}")

    split_subjects: Dict[str, List[int]] = {}
    for key in ("development", "validation"):
        subjects = raw[key]
        for subject_num in subjects:
            if not isinstance(subject_num, int) or isinstance(subject_num, bool):
                raise ValueError(
                    f"{path}의 '{key}'에 정수가 아닌 Subject 번호가 있습니다: {subject_num!r}"
                )
        split_subjects[key] = list(subjects)

    holdout_hit = (set(split_subjects["development"]) | set(split_subjects["validation"])) & (
        _HOLDOUT_SUBJECTS
    )
    if holdout_hit:
        raise ValueError(
            f"{path}에 holdout Subject {sorted(holdout_hit)}가 development/validation에 "
            "포함되어 있습니다. Subject 9~10은 PR4 전까지 절대 사용할 수 없습니다."
        )

    overlap = set(split_subjects["development"]) & set(split_subjects["validation"])
    if overlap:
        raise ValueError(
            f"{path}에서 Subject {sorted(overlap)}가 development/validation 양쪽에 "
            "모두 포함되어 있습니다."
        )

    return split_subjects


# docs/data_sources.md 기준 공식 수량. 이보다 적거나 다르면 데이터셋이 불완전한
# 상태로 생성된 것이므로, 조용히 진행하지 않고 실패시킨다.
_EXPECTED_COUNTS = {
    "development": {"total": 60, "fall": 30, "no_fall": 30},
    "validation": {"total": 20, "fall": 10, "no_fall": 10},
}


@dataclass
class _AnnotationDraft:
    video_id: str
    label: str
    video_path: str
    fall_start_frame: Optional[int]
    review_status: str
    warning: Optional[str]
    txt_count: int
    avi_frame_count: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--dataset-dir",
        required=True,
        help="CAUCAFall v5 루트 (development/validation/holdout 하위 디렉터리를 포함).",
    )
    parser.add_argument("--output-dir", required=True, help="CSV를 생성할 디렉터리")
    parser.add_argument(
        "--split-config",
        default=_DEFAULT_SPLIT_CONFIG_PATH,
        help="development/validation Subject 분할을 정의한 JSON (기본값: configs/caucafall_v5_split.json)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="기존 annotation CSV가 있어도 덮어쓴다 (사람 검수 결과가 사라질 수 있음).",
    )
    return parser.parse_args()


def _contains_holdout_segment(path: Path) -> bool:
    return any(part.lower() == "holdout" for part in path.parts)


def _activity_slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return slug


def _count_video_frames(video_path: Path) -> int:
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise ValueError(f"영상을 열 수 없습니다: {video_path}")
    count = 0
    try:
        while True:
            ret, _ = cap.read()
            if not ret:
                break
            count += 1
    finally:
        cap.release()
    return count


def _read_frame_classes(txt_files: List[Path]) -> List[Optional[str]]:
    classes: List[Optional[str]] = []
    for txt in txt_files:
        content = txt.read_text(encoding="utf-8").strip()
        if not content:
            classes.append(None)
            continue
        classes.append(content.splitlines()[0].split()[0])
    return classes


def process_activity_folder(
    folder: Path, subject_num: int, split_root: Path
) -> _AnnotationDraft:
    """활동 폴더 하나(AVI 1개 + 프레임별 txt N개)에서 annotation 초안 1행을 만든다."""
    avi_files = sorted(folder.glob("*.avi"))
    if len(avi_files) != 1:
        raise ValueError(f"{folder}: AVI 파일이 정확히 1개여야 합니다 (발견 {len(avi_files)}개)")
    avi_path = avi_files[0]

    txt_files = sorted(f for f in folder.glob("*.txt") if f.name != "classes.txt")
    if not txt_files:
        raise ValueError(f"{folder}: txt 라벨 파일이 없습니다")

    classes = _read_frame_classes(txt_files)
    txt_count = len(classes)
    frame_count = _count_video_frames(avi_path)

    warning = None
    if len(classes) > frame_count:
        excess = len(classes) - frame_count
        warning = (
            f"txt {len(classes)}개가 AVI 실제 프레임 수({frame_count})보다 {excess}개 많음 "
            f"-> 뒤에서 {excess}개 제외"
        )
        classes = classes[:frame_count]
    elif len(classes) < frame_count:
        warning = f"txt {len(classes)}개가 AVI 프레임 수({frame_count})보다 적음 (그대로 사용)"

    fall_start_frame = next((i for i, c in enumerate(classes) if c == "1"), None)
    label = "fall" if fall_start_frame is not None else "no_fall"

    video_id = f"S{subject_num}_{_activity_slug(folder.name)}"
    video_path = str(avi_path.relative_to(split_root))

    return _AnnotationDraft(
        video_id=video_id,
        label=label,
        video_path=video_path,
        fall_start_frame=fall_start_frame,
        review_status="pending",
        warning=warning,
        txt_count=txt_count,
        avi_frame_count=frame_count,
    )


def generate_split(
    dataset_dir: Path, split_name: str, split_subjects: Dict[str, List[int]]
) -> List[_AnnotationDraft]:
    split_root = dataset_dir / split_name
    drafts: List[_AnnotationDraft] = []
    for subject_num in split_subjects[split_name]:
        subject_dir = split_root / f"Subject.{subject_num}"
        if not subject_dir.is_dir():
            print(f"  경고: {subject_dir} 없음, 건너뜀")
            continue
        for activity_dir in sorted(p for p in subject_dir.iterdir() if p.is_dir()):
            draft = process_activity_folder(activity_dir, subject_num, split_root)
            if draft.warning:
                print(f"  경고: {draft.video_id}: {draft.warning}")
            drafts.append(draft)
    return drafts


def write_csv(drafts: List[_AnnotationDraft], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=_REQUIRED_COLUMNS, lineterminator="\n")
        writer.writeheader()
        for draft in drafts:
            fall_start_frame = "" if draft.fall_start_frame is None else draft.fall_start_frame
            writer.writerow(
                {
                    "video_id": draft.video_id,
                    "label": draft.label,
                    "video_path": draft.video_path,
                    "fall_start_frame": fall_start_frame,
                    "impact_frame": "",
                    "lying_start_frame": "",
                    "review_status": draft.review_status,
                }
            )


def write_generation_report(drafts: List[_AnnotationDraft], output_path: Path) -> None:
    """txt/AVI 프레임 수 불일치를 CSV로 남긴다 (콘솔 로그만으로는 검수 단계에서 사라짐)."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["video_id", "txt_count", "avi_frame_count", "diff", "warning"]
    with open(output_path, "w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for draft in drafts:
            if draft.warning is None:
                continue
            writer.writerow(
                {
                    "video_id": draft.video_id,
                    "txt_count": draft.txt_count,
                    "avi_frame_count": draft.avi_frame_count,
                    "diff": draft.txt_count - draft.avi_frame_count,
                    "warning": draft.warning,
                }
            )


def guard_dataset_dir(dataset_dir: Path) -> None:
    if _contains_holdout_segment(dataset_dir.resolve()):
        raise SystemExit(
            "Subject 9~10(holdout)은 이 스크립트에서 다루지 않습니다 (docs/data_sources.md)."
        )


def guard_existing_output(output_path: Path, force: bool) -> None:
    """검수 결과가 담긴 기존 CSV를 --force 없이 덮어쓰지 않는다."""
    if output_path.exists() and not force:
        raise SystemExit(
            f"{output_path}가 이미 존재합니다. 사람이 검수한 review_status가 사라질 수 있으니, "
            "덮어쓰려면 --force를 명시하세요."
        )


def verify_expected_counts(drafts: List[_AnnotationDraft], split_name: str) -> None:
    expected = _EXPECTED_COUNTS[split_name]
    fall_count = sum(1 for d in drafts if d.label == "fall")
    no_fall_count = sum(1 for d in drafts if d.label == "no_fall")
    if (
        len(drafts) != expected["total"]
        or fall_count != expected["fall"]
        or no_fall_count != expected["no_fall"]
    ):
        raise SystemExit(
            f"[{split_name}] 예상 수량과 다릅니다 (예상: total={expected['total']} "
            f"fall={expected['fall']} no_fall={expected['no_fall']}, "
            f"실제: total={len(drafts)} fall={fall_count} no_fall={no_fall_count}). "
            "데이터셋이 불완전할 수 있습니다. Subject 디렉터리 존재 여부를 확인하세요."
        )


def main() -> None:
    args = parse_args()
    dataset_dir = Path(args.dataset_dir)
    guard_dataset_dir(dataset_dir)
    split_subjects = load_split_subjects(args.split_config)

    output_dir = Path(args.output_dir)
    for split_name in ("development", "validation"):
        output_path = output_dir / f"{split_name}_annotations.csv"
        guard_existing_output(output_path, args.force)

        print(f"[{split_name}] annotation 생성 중...")
        drafts = generate_split(dataset_dir, split_name, split_subjects)
        verify_expected_counts(drafts, split_name)

        fall_count = sum(1 for d in drafts if d.label == "fall")
        no_fall_count = sum(1 for d in drafts if d.label == "no_fall")
        write_csv(drafts, output_path)
        report_path = output_dir / f"{split_name}_generation_report.csv"
        write_generation_report(drafts, report_path)
        print(f"  {len(drafts)}개 영상 (fall {fall_count}, no_fall {no_fall_count}) -> {output_path}")
        print(f"  프레임 수 불일치 리포트 -> {report_path}")


if __name__ == "__main__":
    main()
