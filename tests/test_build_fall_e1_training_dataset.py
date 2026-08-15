"""실제 RGB E1 학습 목록 조립 테스트."""

from __future__ import annotations

import csv
import hashlib
import json
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import build_fall_e1_training_dataset as builder  # noqa: E402


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sample(root: Path, split: str, sample_id: str, class_id: int) -> None:
    image = root / "images" / split / f"{sample_id}.png"
    label = root / "labels" / split / f"{sample_id}.txt"
    image.parent.mkdir(parents=True, exist_ok=True)
    label.parent.mkdir(parents=True, exist_ok=True)
    image.write_bytes(f"image:{sample_id}".encode())
    label.write_text(f"{class_id} 0.5 0.5 0.5 0.5\n", encoding="ascii")


def _base_dataset(tmp_path: Path) -> Path:
    root = tmp_path / "base"
    train = [
        ("S1_fall_forward_f001", 1),
        ("S2_fall_backwards_f001", 1),
        ("S1_walk_n001", 0),
        ("S1_walk_n002", 0),
        ("S2_sit_down_n001", 0),
        ("S2_sit_down_n002", 0),
    ]
    val = [("S6_fall_forward_v001", 1), ("S6_walk_v001", 0)]
    for sample_id, class_id in train:
        _sample(root, "train", sample_id, class_id)
    for sample_id, class_id in val:
        _sample(root, "val", sample_id, class_id)
    (root / "dataset_manifest.json").write_text(
        json.dumps(
            {
                "train_subjects": [1, 2, 3, 4, 5],
                "val_subjects": [6],
                "splits": {
                    "train": {"matched_frames": len(train)},
                    "val": {"matched_frames": len(val)},
                },
            }
        ),
        encoding="utf-8",
    )
    return root


def _supplement(tmp_path: Path, split_role: str = "train_candidate") -> Path:
    root = tmp_path / "supplement"
    sample_id = "upfall_s01_sitting_f000010"
    _sample(root, "train", sample_id, 0)
    image = root / "images/train" / f"{sample_id}.png"
    label = root / "labels/train" / f"{sample_id}.txt"
    frames_path = root / "frames.csv"
    frames_path.parent.mkdir(parents=True, exist_ok=True)
    with frames_path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "sample_id",
                "video_id",
                "image_path",
                "label_path",
                "image_sha256",
                "label_sha256",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "sample_id": sample_id,
                "video_id": "upfall_s01_sitting",
                "image_path": f"images/train/{sample_id}.png",
                "label_path": f"labels/train/{sample_id}.txt",
                "image_sha256": _sha256(image),
                "label_sha256": _sha256(label),
            }
        )
    (root / "supplement_manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "real_rgb_e1_frame_supplement_v1",
                "purpose": "train-only E1 nofall supplement",
                "source_split_role": split_role,
                "class_mapping": {"0": "nofall", "1": "fall"},
                "sources": {"source_dataset": "up_fall"},
                "frame_count": 1,
                "selected_event_count": 1,
                "frames_csv_sha256": _sha256(frames_path),
            }
        ),
        encoding="utf-8",
    )
    return root


def _recorded_supplement(tmp_path: Path, actor_id: str = "A01") -> Path:
    root = tmp_path / "recorded_supplement"
    samples = [
        (f"p4_{actor_id}_fall_f00010", 1),
        (f"p4_{actor_id}_sit_f00010", 0),
    ]
    rows = []
    for sample_id, class_id in samples:
        _sample(root, "train", sample_id, class_id)
        image = root / "images/train" / f"{sample_id}.png"
        label = root / "labels/train" / f"{sample_id}.txt"
        rows.append(
            {
                "sample_id": sample_id,
                "video_id": sample_id,
                "image_path": f"images/train/{sample_id}.png",
                "label_path": f"labels/train/{sample_id}.txt",
                "image_sha256": _sha256(image),
                "label_sha256": _sha256(label),
            }
        )
    frames_path = root / "frames.csv"
    with frames_path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (root / "supplement_manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "phase4_recorded_e1_frame_supplement_v1",
                "purpose": "train-only Phase 4 recorded E1 supplement",
                "source_split_role": "diagnostic",
                "training_actor_ids": [actor_id],
                "class_mapping": {"0": "nofall", "1": "fall"},
                "class_counts": {"nofall": 1, "fall": 1},
                "sources": {"source_dataset": "phase4_recorded_2026_08_07"},
                "frame_count": 2,
                "frames_csv_sha256": _sha256(frames_path),
            }
        ),
        encoding="utf-8",
    )
    return root


def test_builds_balanced_replay_without_copying_images(tmp_path):
    base = _base_dataset(tmp_path)
    supplement = _supplement(tmp_path)
    output = tmp_path / "variant"

    manifest = builder.build_dataset(base, [supplement], output, 1.0, False)

    assert manifest["counts"] == {
        "base_train_fall": 2,
        "base_train_nofall_available": 4,
        "base_train_nofall_selected": 2,
        "real_rgb_nofall": 1,
        "real_rgb_fall": 0,
        "supplement_training_entries": 1,
        "train_total": 5,
        "val_total": 2,
    }
    train_paths = (output / "train.txt").read_text().splitlines()
    val_paths = (output / "val.txt").read_text().splitlines()
    assert len(train_paths) == 5
    assert len(val_paths) == 2
    assert any("upfall_s01_sitting" in path for path in train_paths)
    assert all("upfall" not in path for path in val_paths)
    payload = yaml.safe_load((output / "dataset.yaml").read_text())
    assert payload["names"] == {0: "nofall", 1: "fall"}
    assert payload["train"] == str((output / "train.txt").resolve())
    assert not (output / "images").exists()


def test_balanced_sampling_covers_each_available_group(tmp_path):
    base = _base_dataset(tmp_path)
    train, _, _, _ = builder.load_base_dataset(base)
    nofall = [record for record in train if record["class_id"] == 0]

    selected = builder.select_balanced_nofall(nofall, 2)

    assert {builder._nofall_group(record["sample_id"]) for record in selected} == {
        (1, "walk"),
        (2, "sit_down"),
    }


def test_nofall_group_accepts_prefall_frame_from_fall_activity():
    assert builder._nofall_group("S1_fall_backwards_cas100001") == (
        1,
        "fall_backwards",
    )


def test_rejects_validation_supplement(tmp_path):
    base = _base_dataset(tmp_path)
    supplement = _supplement(tmp_path, split_role="validation")

    with pytest.raises(builder.DatasetBuildError, match="train_candidate"):
        builder.build_dataset(base, [supplement], tmp_path / "variant", 1.0, False)


def test_rejects_tampered_supplement_frame(tmp_path):
    base = _base_dataset(tmp_path)
    supplement = _supplement(tmp_path)
    next((supplement / "images/train").glob("*.png")).write_bytes(b"tampered")

    with pytest.raises(builder.DatasetBuildError, match="SHA-256"):
        builder.build_dataset(base, [supplement], tmp_path / "variant", 1.0, False)


@pytest.mark.parametrize("ratio", [0.0, -1.0, 3.1, float("inf")])
def test_rejects_invalid_nofall_ratio(tmp_path, ratio):
    with pytest.raises(builder.DatasetBuildError, match="ratio"):
        builder.build_dataset(
            _base_dataset(tmp_path),
            [_supplement(tmp_path)],
            tmp_path / "variant",
            ratio,
            False,
        )


def test_rejects_fall_class_in_hard_negative_supplement(tmp_path):
    base = _base_dataset(tmp_path)
    supplement = _supplement(tmp_path)
    label = next((supplement / "labels/train").glob("*.txt"))
    label.write_text("1 0.5 0.5 0.5 0.5\n", encoding="ascii")
    frames = list(csv.DictReader((supplement / "frames.csv").open(encoding="utf-8")))
    frames[0]["label_sha256"] = _sha256(label)
    with (supplement / "frames.csv").open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(frames[0]))
        writer.writeheader()
        writer.writerows(frames)
    manifest_path = supplement / "supplement_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["frames_csv_sha256"] = _sha256(supplement / "frames.csv")
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(builder.DatasetBuildError, match="nofall"):
        builder.build_dataset(base, [supplement], tmp_path / "variant", 1.0, False)


def test_accepts_recorded_a01_mixed_class_supplement(tmp_path):
    base = _base_dataset(tmp_path)
    supplement = _recorded_supplement(tmp_path)

    manifest = builder.build_dataset(
        base, [supplement], tmp_path / "variant", 1.0, False
    )

    assert manifest["counts"]["real_rgb_nofall"] == 1
    assert manifest["counts"]["real_rgb_fall"] == 1
    assert manifest["counts"]["supplement_training_entries"] == 2
    assert manifest["counts"]["train_total"] == 6


def test_repeats_only_recorded_supplement_for_domain_weighting(tmp_path):
    base = _base_dataset(tmp_path)
    recorded = _recorded_supplement(tmp_path)

    manifest = builder.build_dataset(
        base,
        [recorded],
        tmp_path / "variant",
        1.0,
        False,
        recorded_supplement_repeat=3,
    )

    assert manifest["counts"]["real_rgb_nofall"] == 1
    assert manifest["counts"]["real_rgb_fall"] == 1
    assert manifest["counts"]["supplement_training_entries"] == 6
    assert manifest["counts"]["train_total"] == 10


def test_rejects_recorded_a02_training_supplement(tmp_path):
    base = _base_dataset(tmp_path)
    supplement = _recorded_supplement(tmp_path, actor_id="A02")

    with pytest.raises(builder.DatasetBuildError, match="A01"):
        builder.build_dataset(base, [supplement], tmp_path / "variant", 1.0, False)
