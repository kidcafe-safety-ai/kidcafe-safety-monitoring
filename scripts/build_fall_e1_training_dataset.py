"""CAUCAFall replay와 검수된 실제 RGB supplement로 E1 학습 목록을 만든다.

이미지를 복사하지 않고 Ultralytics가 지원하는 ``train.txt``/``val.txt``를
생성한다. CAUCAFall의 fall frame은 모두 replay하고, 강하게 상관된 nofall
frame은 Subject·활동별로 균등하게 줄인다. 실제 RGB supplement는
``train_candidate``에서 사람이 승인한 class 0 frame만 허용한다.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import shutil
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Iterable, Sequence

import yaml


SCHEMA_VERSION = "fall_e1_training_dataset_v1"
SUPPLEMENT_SCHEMA_VERSION = "real_rgb_e1_frame_supplement_v1"
BASE_TRAIN_SUBJECTS = [1, 2, 3, 4, 5]
BASE_VAL_SUBJECTS = [6]
NOFALL_ACTIVITIES = (
    "pick_up_object",
    "sit_down",
    "kneel",
    "walk",
    "hop",
)
REQUIRED_FRAME_COLUMNS = {
    "sample_id",
    "video_id",
    "image_path",
    "label_path",
    "image_sha256",
    "label_sha256",
}


class DatasetBuildError(ValueError):
    """입력 데이터나 provenance가 E1 계약을 만족하지 않을 때 발생한다."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-dataset", required=True)
    parser.add_argument(
        "--supplement",
        action="append",
        default=[],
        help="materialize_real_rgb_e1_frames.py 출력. 여러 번 지정 가능",
    )
    parser.add_argument("--output-dir", required=True)
    parser.add_argument(
        "--base-nofall-to-fall-ratio",
        type=float,
        default=1.0,
        help="CAUCAFall train nofall replay 수 / fall replay 수",
    )
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
        raise DatasetBuildError(f"{description} 파일이 없습니다: {path}")
    try:
        with open(path, "r", encoding="utf-8") as file:
            payload = json.load(file)
    except (OSError, json.JSONDecodeError) as exc:
        raise DatasetBuildError(f"{description} JSON을 읽을 수 없습니다: {exc}") from exc
    if not isinstance(payload, dict):
        raise DatasetBuildError(f"{description} JSON root는 객체여야 합니다.")
    return payload


def _label_classes(path: Path) -> tuple[int, ...]:
    try:
        lines = path.read_text(encoding="ascii").splitlines()
    except (OSError, UnicodeError) as exc:
        raise DatasetBuildError(f"YOLO label을 읽을 수 없습니다: {path}") from exc
    if not lines:
        raise DatasetBuildError(f"YOLO label이 비어 있습니다: {path}")
    classes = []
    for line_number, line in enumerate(lines, start=1):
        parts = line.split()
        if len(parts) != 5 or parts[0] not in {"0", "1"}:
            raise DatasetBuildError(
                f"YOLO label 형식이 올바르지 않습니다: {path}:{line_number}"
            )
        try:
            values = [float(value) for value in parts[1:]]
        except ValueError as exc:
            raise DatasetBuildError(
                f"YOLO bbox 숫자를 읽을 수 없습니다: {path}:{line_number}"
            ) from exc
        if (
            any(not math.isfinite(value) or not 0.0 <= value <= 1.0 for value in values)
            or values[2] <= 0
            or values[3] <= 0
        ):
            raise DatasetBuildError(
                f"YOLO bbox가 올바르지 않습니다: {path}:{line_number}"
            )
        classes.append(int(parts[0]))
    return tuple(classes)


def _load_pairs(images_dir: Path, labels_dir: Path) -> list[dict]:
    if not images_dir.is_dir() or not labels_dir.is_dir():
        raise DatasetBuildError(f"images/labels 디렉터리가 없습니다: {images_dir}")
    images = sorted(images_dir.glob("*.png"))
    labels = {path.stem: path for path in labels_dir.glob("*.txt")}
    if not images:
        raise DatasetBuildError(f"PNG가 없습니다: {images_dir}")
    if len(labels) != len(images):
        raise DatasetBuildError(
            f"image/label 수가 다릅니다: {images_dir}: {len(images)}/{len(labels)}"
        )
    records = []
    for image in images:
        label = labels.get(image.stem)
        if label is None:
            raise DatasetBuildError(f"대응 label이 없습니다: {image}")
        classes = _label_classes(label)
        if len(set(classes)) != 1:
            raise DatasetBuildError(f"한 frame에 fall/nofall label이 섞였습니다: {label}")
        records.append(
            {
                "sample_id": image.stem,
                "image": image.resolve(),
                "label": label.resolve(),
                "class_id": classes[0],
            }
        )
    return records


def load_base_dataset(base_dir: Path) -> tuple[list[dict], list[dict], dict, Path]:
    manifest_path = base_dir / "dataset_manifest.json"
    manifest = _load_json(manifest_path, "base dataset manifest")
    if manifest.get("train_subjects") != BASE_TRAIN_SUBJECTS:
        raise DatasetBuildError("base train Subject는 1-5여야 합니다.")
    if manifest.get("val_subjects") != BASE_VAL_SUBJECTS:
        raise DatasetBuildError("base val Subject는 6이어야 합니다.")
    train = _load_pairs(base_dir / "images/train", base_dir / "labels/train")
    val = _load_pairs(base_dir / "images/val", base_dir / "labels/val")
    for split_name, records in (("train", train), ("val", val)):
        expected = manifest.get("splits", {}).get(split_name, {}).get("matched_frames")
        if expected != len(records):
            raise DatasetBuildError(
                f"base {split_name} 수가 manifest와 다릅니다: {len(records)}/{expected}"
            )
    return train, val, manifest, manifest_path


def _nofall_group(sample_id: str) -> tuple[int, str]:
    if not sample_id.startswith("S") or "_" not in sample_id:
        raise DatasetBuildError(f"CAUCAFall sample_id가 올바르지 않습니다: {sample_id}")
    subject_text, remainder = sample_id[1:].split("_", 1)
    try:
        subject = int(subject_text)
    except ValueError as exc:
        raise DatasetBuildError(f"CAUCAFall Subject를 읽을 수 없습니다: {sample_id}") from exc
    for activity in NOFALL_ACTIVITIES:
        if remainder.startswith(f"{activity}_"):
            return subject, activity
    raise DatasetBuildError(f"CAUCAFall nofall 활동을 읽을 수 없습니다: {sample_id}")


def _evenly_spaced(records: Sequence[dict], count: int) -> list[dict]:
    if count <= 0:
        return []
    if count >= len(records):
        return list(records)
    if count == 1:
        return [records[len(records) // 2]]
    indexes = [round(index * (len(records) - 1) / (count - 1)) for index in range(count)]
    return [records[index] for index in indexes]


def select_balanced_nofall(records: Sequence[dict], target: int) -> list[dict]:
    groups: dict[tuple[int, str], list[dict]] = defaultdict(list)
    for record in records:
        groups[_nofall_group(record["sample_id"])].append(record)
    if not groups or target <= 0:
        raise DatasetBuildError("base nofall replay 목표와 그룹은 1 이상이어야 합니다.")
    if target >= len(records):
        return sorted(records, key=lambda item: item["sample_id"])

    quotas = {key: 0 for key in groups}
    remaining = target
    ordered_keys = sorted(groups)
    while remaining:
        progressed = False
        for key in ordered_keys:
            if quotas[key] < len(groups[key]):
                quotas[key] += 1
                remaining -= 1
                progressed = True
                if remaining == 0:
                    break
        if not progressed:
            raise DatasetBuildError("base nofall replay quota를 채울 수 없습니다.")

    selected = []
    for key in ordered_keys:
        ordered = sorted(groups[key], key=lambda item: item["sample_id"])
        selected.extend(_evenly_spaced(ordered, quotas[key]))
    return sorted(selected, key=lambda item: item["sample_id"])


def _load_frames_csv(path: Path) -> list[dict]:
    if not path.is_file():
        raise DatasetBuildError(f"supplement frames.csv가 없습니다: {path}")
    with open(path, "r", encoding="utf-8", newline="") as file:
        reader = csv.DictReader(file)
        missing = REQUIRED_FRAME_COLUMNS - set(reader.fieldnames or [])
        if missing:
            raise DatasetBuildError(f"frames.csv 필수 컬럼이 없습니다: {sorted(missing)}")
        return list(reader)


def load_supplement(path: Path) -> tuple[list[dict], dict]:
    manifest_path = path / "supplement_manifest.json"
    manifest = _load_json(manifest_path, "supplement manifest")
    if manifest.get("schema_version") != SUPPLEMENT_SCHEMA_VERSION:
        raise DatasetBuildError(f"supplement schema가 다릅니다: {path}")
    if manifest.get("purpose") != "train-only E1 nofall supplement":
        raise DatasetBuildError(f"train-only supplement가 아닙니다: {path}")
    if manifest.get("source_split_role") != "train_candidate":
        raise DatasetBuildError(f"supplement source가 train_candidate가 아닙니다: {path}")
    if manifest.get("class_mapping") != {"0": "nofall", "1": "fall"}:
        raise DatasetBuildError(f"supplement class mapping이 다릅니다: {path}")

    frames_path = path / "frames.csv"
    if manifest.get("frames_csv_sha256") != _sha256(frames_path):
        raise DatasetBuildError(f"supplement frames.csv SHA-256이 다릅니다: {path}")
    rows = _load_frames_csv(frames_path)
    records = _load_pairs(path / "images/train", path / "labels/train")
    if manifest.get("frame_count") != len(rows) or len(records) != len(rows):
        raise DatasetBuildError(f"supplement frame 수가 manifest와 다릅니다: {path}")
    rows_by_id = {row["sample_id"]: row for row in rows}
    if len(rows_by_id) != len(rows):
        raise DatasetBuildError(f"supplement sample_id가 중복됩니다: {path}")
    for record in records:
        row = rows_by_id.get(record["sample_id"])
        if row is None:
            raise DatasetBuildError(f"frames.csv에 sample이 없습니다: {record['sample_id']}")
        if record["class_id"] != 0:
            raise DatasetBuildError(f"supplement에는 nofall만 허용합니다: {record['label']}")
        if row["image_sha256"] != _sha256(record["image"]):
            raise DatasetBuildError(f"supplement image SHA-256이 다릅니다: {record['image']}")
        if row["label_sha256"] != _sha256(record["label"]):
            raise DatasetBuildError(f"supplement label SHA-256이 다릅니다: {record['label']}")
        record["source_dataset"] = manifest.get("sources", {}).get("source_dataset")
    return records, {
        "path": str(path.resolve()),
        "manifest_sha256": _sha256(manifest_path),
        "frames_csv_sha256": _sha256(frames_path),
        "frame_count": len(records),
        "selected_event_count": manifest.get("selected_event_count"),
        "source_dataset": manifest.get("sources", {}).get("source_dataset"),
    }


def _write_lines(path: Path, records: Iterable[dict]) -> None:
    lines = [str(record["image"]) for record in records]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _replace_output(staging_dir: Path, output_dir: Path, force: bool) -> None:
    if output_dir.exists() and not force:
        raise DatasetBuildError(f"{output_dir}가 이미 있습니다 (--force로 전체 교체).")
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


def build_dataset(
    base_dir: Path,
    supplement_dirs: Sequence[Path],
    output_dir: Path,
    base_nofall_to_fall_ratio: float,
    force: bool,
) -> dict:
    if (
        not math.isfinite(base_nofall_to_fall_ratio)
        or base_nofall_to_fall_ratio <= 0
        or base_nofall_to_fall_ratio > 3
    ):
        raise DatasetBuildError("base-nofall-to-fall-ratio는 0보다 크고 3 이하여야 합니다.")
    if not supplement_dirs:
        raise DatasetBuildError("--supplement를 1개 이상 지정해야 합니다.")

    base_train, base_val, _, base_manifest_path = load_base_dataset(base_dir)
    base_fall = [record for record in base_train if record["class_id"] == 1]
    base_nofall = [record for record in base_train if record["class_id"] == 0]
    nofall_target = min(
        len(base_nofall), math.ceil(len(base_fall) * base_nofall_to_fall_ratio)
    )
    selected_nofall = select_balanced_nofall(base_nofall, nofall_target)

    supplements = []
    supplement_sources = []
    for supplement_dir in supplement_dirs:
        records, provenance = load_supplement(supplement_dir)
        supplements.extend(records)
        supplement_sources.append(provenance)
    all_sample_ids = [record["sample_id"] for record in supplements]
    if len(all_sample_ids) != len(set(all_sample_ids)):
        raise DatasetBuildError("여러 supplement 사이에 sample_id가 중복됩니다.")

    train = sorted(
        [*base_fall, *selected_nofall, *supplements],
        key=lambda item: (item["class_id"], item["sample_id"], str(item["image"])),
    )
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    staging_dir = Path(
        tempfile.mkdtemp(prefix=f".{output_dir.name}.build-", dir=output_dir.parent)
    )
    try:
        final_train_path = output_dir.resolve() / "train.txt"
        final_val_path = output_dir.resolve() / "val.txt"
        _write_lines(staging_dir / "train.txt", train)
        _write_lines(staging_dir / "val.txt", base_val)
        yaml_payload = {
            "path": "/",
            "train": str(final_train_path),
            "val": str(final_val_path),
            "names": {0: "nofall", 1: "fall"},
        }
        yaml_path = staging_dir / "dataset.yaml"
        yaml_path.write_text(
            yaml.safe_dump(yaml_payload, sort_keys=False, allow_unicode=False),
            encoding="ascii",
        )
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "purpose": "E1 real RGB hard-negative fine-tuning",
            "policy": {
                "base_fall_replay": "all CAUCAFall S1-5 fall frames",
                "base_nofall_sampling": "equal Subject/activity quotas, temporal spacing",
                "base_nofall_to_fall_ratio": base_nofall_to_fall_ratio,
                "supplement": "reviewed model-involved train_candidate nofall only",
                "validation": "unchanged CAUCAFall Subject 6",
            },
            "sources": {
                "base_dataset": {
                    "path": str(base_dir.resolve()),
                    "manifest_sha256": _sha256(base_manifest_path),
                },
                "supplements": supplement_sources,
            },
            "counts": {
                "base_train_fall": len(base_fall),
                "base_train_nofall_available": len(base_nofall),
                "base_train_nofall_selected": len(selected_nofall),
                "real_rgb_nofall": len(supplements),
                "train_total": len(train),
                "val_total": len(base_val),
            },
            "artifacts": {
                "train_txt_sha256": _sha256(staging_dir / "train.txt"),
                "val_txt_sha256": _sha256(staging_dir / "val.txt"),
                "dataset_yaml_sha256": _sha256(yaml_path),
            },
        }
        (staging_dir / "training_dataset_manifest.json").write_text(
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
        manifest = build_dataset(
            Path(args.base_dataset),
            [Path(value) for value in args.supplement],
            Path(args.output_dir),
            args.base_nofall_to_fall_ratio,
            args.force,
        )
    except DatasetBuildError as exc:
        raise SystemExit(str(exc)) from exc
    counts = manifest["counts"]
    print(
        "E1 학습 목록: "
        f"train={counts['train_total']} "
        f"(fall replay={counts['base_train_fall']}, "
        f"base nofall={counts['base_train_nofall_selected']}, "
        f"real RGB nofall={counts['real_rgb_nofall']}), "
        f"val={counts['val_total']}"
    )


if __name__ == "__main__":
    main()
