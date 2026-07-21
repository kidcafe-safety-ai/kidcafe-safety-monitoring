"""CAUCAFall annotation V2 검수 초안을 생성한다.

기존 annotation 출력은 유지한다. 원본 class 0->1 전환은
`dataset_fall_label_frame`으로 보존하고, 사람이 `fall_start_frame`,
`impact_frame`, `lying_start_frame`을 검수할 별도 V2 CSV를 만든다.

v1 스크립트가 이미 검증한 로직(txt/AVI 프레임 수 불일치 보정, Subject 분할,
holdout 차단, 예상 수량 검증)을 그대로 재사용한다 — class 0->1 전환 계산은
v1과 동일해야 `dataset_fall_label_frame`이 실제 원본 라벨과 어긋나지 않는다.

fall 행은 검수 전까지 `fall_start_frame`/`impact_frame`/`lying_start_frame`을
비워 `review_status=pending`으로 둔다. no_fall 행은 동작 시점 필드가 애초에
필요 없으므로 v1과 동일하게 비워 두고 `review_status=pending`으로 시작한다
(auto-verify는 review_caucafall_annotations.py --auto-verify-no-fall로 v2
CSV에도 그대로 적용 가능).

--seed-needs-review-from으로 기존 v1 CSV를 넘기면, v1에서 이미
`review_status=needs_review`로 표시된 video_id(예: S6_fall_backwards)를 v2
CSV에도 동일하게 seed한다 — 사람이 이미 내린 "검수 보류" 판단을 v2에서
처음부터 다시 발견하지 않아도 되게 하기 위함이다. 최종 reviewed 판정은 여전히
review_caucafall_annotations.py --annotation-version v2에서 사람이 내린다.
development/validation 두 CSV를 항상 함께 생성하므로, needs_review를 양쪽에서
모두 seed하려면 --seed-needs-review-from을 두 번 넘긴다(합집합 처리).

Usage:
    .venv/bin/python scripts/generate_caucafall_annotations_v2.py \
        --dataset-dir data/datasets/caucafall/v5 \
        --output-dir data/annotations/caucafall_v5 \
        --seed-needs-review-from data/annotations/caucafall_v5/development_annotations.csv \
        --seed-needs-review-from data/annotations/caucafall_v5/validation_annotations.csv
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import List, Set

import generate_caucafall_annotations as v1
from generate_caucafall_annotations import _AnnotationDraft

_REQUIRED_COLUMNS = [
    "video_id",
    "label",
    "video_path",
    "dataset_fall_label_frame",
    "fall_start_frame",
    "impact_frame",
    "lying_start_frame",
    "review_status",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--dataset-dir",
        required=True,
        help="CAUCAFall v5 루트 (development/validation 하위 디렉터리를 포함).",
    )
    parser.add_argument("--output-dir", required=True, help="V2 CSV를 생성할 디렉터리")
    parser.add_argument(
        "--split-config",
        default=v1._DEFAULT_SPLIT_CONFIG_PATH,
        help="development/validation Subject 분할을 정의한 JSON",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="기존 V2 annotation CSV가 있어도 덮어쓴다 (사람 검수 결과가 사라질 수 있음).",
    )
    parser.add_argument(
        "--seed-needs-review-from",
        action="append",
        default=None,
        help=(
            "기존 v1 annotation CSV 경로. review_status=needs_review인 video_id를 "
            "v2 CSV에도 동일하게 seed한다. 여러 번 넘기면(예: development_annotations.csv와 "
            "validation_annotations.csv 둘 다) 합집합으로 처리한다 — 이 스크립트는 항상 "
            "development/validation 두 CSV를 함께 생성하므로, 한 split의 CSV만 넘기고 "
            "--force로 두 번 실행하면 먼저 실행에서 seed된 결과가 두 번째 실행에서 "
            "지워진다."
        ),
    )
    return parser.parse_args()


_SEED_REQUIRED_COLUMNS = {"video_id", "review_status"}


def load_needs_review_ids(path: str) -> Set[str]:
    with open(path, "r", encoding="utf-8", newline="") as file:
        reader = csv.DictReader(file)
        missing_columns = _SEED_REQUIRED_COLUMNS - set(reader.fieldnames or [])
        if missing_columns:
            raise ValueError(
                f"{path}: seed CSV에 필수 컬럼이 없습니다: {sorted(missing_columns)}"
            )
        ids: Set[str] = set()
        for row_number, row in enumerate(reader, start=2):  # 헤더가 1행
            if (row.get("review_status") or "").strip() != "needs_review":
                continue
            video_id = (row.get("video_id") or "").strip()
            if not video_id:
                raise ValueError(
                    f"{path}:{row_number}: review_status=needs_review인데 video_id가 "
                    "비어 있습니다."
                )
            ids.add(video_id)
        return ids


def load_needs_review_ids_from_all(paths: List[str]) -> Set[str]:
    ids: Set[str] = set()
    for path in paths:
        ids |= load_needs_review_ids(path)
    return ids


def write_v2_csv(
    drafts: List[_AnnotationDraft], output_path: Path, needs_review_ids: Set[str]
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=_REQUIRED_COLUMNS, lineterminator="\n")
        writer.writeheader()
        for draft in drafts:
            is_fall = draft.label == "fall"
            dataset_fall_label_frame = (
                draft.fall_start_frame if is_fall and draft.fall_start_frame is not None else ""
            )
            review_status = "needs_review" if draft.video_id in needs_review_ids else "pending"
            writer.writerow(
                {
                    "video_id": draft.video_id,
                    "label": draft.label,
                    "video_path": draft.video_path,
                    "dataset_fall_label_frame": dataset_fall_label_frame,
                    "fall_start_frame": "",
                    "impact_frame": "",
                    "lying_start_frame": "",
                    "review_status": review_status,
                }
            )


def main() -> None:
    args = parse_args()
    dataset_dir = Path(args.dataset_dir)
    v1.guard_dataset_dir(dataset_dir)
    split_subjects = v1.load_split_subjects(args.split_config)

    needs_review_ids: Set[str] = set()
    if args.seed_needs_review_from:
        needs_review_ids = load_needs_review_ids_from_all(args.seed_needs_review_from)

    output_dir = Path(args.output_dir)
    output_paths = {
        split_name: output_dir / f"{split_name}_annotations_v2.csv"
        for split_name in ("development", "validation")
    }
    # 두 split 모두 쓰기 전에 먼저 검사한다 — development는 통과하고 validation만
    # 이미 존재해서 실패하면, development는 이미 덮어써진 채 절반만 생성된
    # 상태로 남는다.
    for output_path in output_paths.values():
        v1.guard_existing_output(output_path, args.force)

    for split_name, output_path in output_paths.items():
        print(f"[{split_name}] annotation V2 생성 중...")
        drafts = v1.generate_split(dataset_dir, split_name, split_subjects)
        v1.verify_expected_counts(drafts, split_name)

        fall_count = sum(1 for d in drafts if d.label == "fall")
        no_fall_count = sum(1 for d in drafts if d.label == "no_fall")
        write_v2_csv(drafts, output_path, needs_review_ids)
        print(
            f"  {len(drafts)}개 영상 (fall {fall_count}, no_fall {no_fall_count}) -> {output_path}"
        )
        seeded = sorted(
            d.video_id for d in drafts if d.video_id in needs_review_ids
        )
        if seeded:
            print(f"  needs_review로 seed됨: {seeded}")


if __name__ == "__main__":
    main()
