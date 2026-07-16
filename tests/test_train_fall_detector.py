"""scripts/train_fall_detector.py 테스트.

실제 GPU 학습(Colab 전제)은 여기서 검증하지 않는다. 설정 로딩·검증과 산출물
기록(run manifest) 로직만 다룬다 — ultralytics.YOLO.train() 자체는 이
테스트의 대상이 아니다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import train_fall_detector as train  # noqa: E402


def _write_config(path: Path, **overrides) -> None:
    config = {
        "model": "yolo26n.pt",
        "task": "detect",
        "data": "configs/fall_training_dataset.yaml",
        "classes": ["nofall", "fall"],
        "imgsz": 640,
        "epochs": 50,
        "patience": 10,
        "seed": 42,
        "device": "",
        "project": "outputs/fall_training/runs",
        "name": "fall_detector",
    }
    config.update(overrides)
    path.write_text(json.dumps(config), encoding="utf-8")


class TestTrainingConfigFromFile:
    def test_loads_valid_config(self, tmp_path):
        path = tmp_path / "config.json"
        _write_config(path)

        config = train.TrainingConfig.from_file(str(path))

        assert config.model == "yolo26n.pt"
        assert config.epochs == 50
        assert config.classes == ["nofall", "fall"]

    def test_missing_field_raises(self, tmp_path):
        path = tmp_path / "config.json"
        path.write_text(json.dumps({"model": "yolo26n.pt"}), encoding="utf-8")

        with pytest.raises(ValueError, match="필수 필드"):
            train.TrainingConfig.from_file(str(path))

    def test_wrong_class_count_raises(self, tmp_path):
        path = tmp_path / "config.json"
        _write_config(path, classes=["nofall", "fall", "extra"])

        with pytest.raises(ValueError, match="nofall"):
            train.TrainingConfig.from_file(str(path))

    def test_wrong_class_order_raises(self, tmp_path):
        """순서가 뒤바뀌면(fall이 0, nofall이 1) fall_training_dataset.yaml과 어긋난다."""
        path = tmp_path / "config.json"
        _write_config(path, classes=["fall", "nofall"])

        with pytest.raises(ValueError, match="nofall"):
            train.TrainingConfig.from_file(str(path))


class TestCollectSplitManifest:
    def test_lists_png_files_per_split(self, tmp_path):
        dataset_root = tmp_path / "dataset"
        (dataset_root / "images" / "train").mkdir(parents=True)
        (dataset_root / "images" / "val").mkdir(parents=True)
        (dataset_root / "images" / "train" / "a.png").write_bytes(b"")
        (dataset_root / "images" / "train" / "b.png").write_bytes(b"")
        (dataset_root / "images" / "val" / "c.png").write_bytes(b"")

        data_yaml = tmp_path / "configs" / "fall_training_dataset.yaml"
        data_yaml.parent.mkdir(parents=True)
        data_yaml.write_text(
            f"path: {dataset_root}\ntrain: images/train\nval: images/val\n"
            "names:\n  0: nofall\n  1: fall\n"
        )

        manifest = train._collect_split_manifest(data_yaml)

        assert manifest["train"] == ["a.png", "b.png"]
        assert manifest["val"] == ["c.png"]

    def test_missing_split_dir_is_empty_list(self, tmp_path):
        dataset_root = tmp_path / "dataset"
        dataset_root.mkdir()
        data_yaml = tmp_path / "fall_training_dataset.yaml"
        data_yaml.write_text(
            f"path: {dataset_root}\ntrain: images/train\nval: images/val\n"
            "names:\n  0: nofall\n  1: fall\n"
        )

        manifest = train._collect_split_manifest(data_yaml)

        assert manifest == {"train": [], "val": []}


class TestWriteRunManifest:
    def test_writes_manifest_with_sha256_when_best_pt_exists(self, tmp_path, monkeypatch):
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        weights_dir = run_dir / "weights"
        weights_dir.mkdir()
        best_pt = weights_dir / "best.pt"
        best_pt.write_bytes(b"fake weights")

        data_yaml = tmp_path / "fall_training_dataset.yaml"
        dataset_root = tmp_path / "dataset"
        (dataset_root / "images" / "train").mkdir(parents=True)
        (dataset_root / "images" / "val").mkdir(parents=True)
        data_yaml.write_text(
            f"path: {dataset_root}\ntrain: images/train\nval: images/val\n"
            "names:\n  0: nofall\n  1: fall\n"
        )

        config = train.TrainingConfig(
            model="yolo26n.pt",
            task="detect",
            data=str(data_yaml),
            classes=["nofall", "fall"],
            imgsz=640,
            epochs=50,
            patience=10,
            seed=42,
            device="",
            project=str(tmp_path),
            name="run",
        )

        train.write_run_manifest(run_dir, config, best_pt)

        manifest_path = run_dir / "run_manifest.json"
        assert manifest_path.is_file()
        manifest = json.loads(manifest_path.read_text())
        assert manifest["config"]["model"] == "yolo26n.pt"
        assert "best_pt_sha256" in manifest
        assert manifest["best_pt_path"] == str(best_pt)

    def test_records_cli_overridden_epochs_and_device_not_config_defaults(self, tmp_path):
        """--epochs/--device로 재정의했으면 manifest에는 실제 사용값이 남아야 한다."""
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        data_yaml = tmp_path / "fall_training_dataset.yaml"
        dataset_root = tmp_path / "dataset"
        dataset_root.mkdir()
        data_yaml.write_text(
            f"path: {dataset_root}\ntrain: images/train\nval: images/val\n"
            "names:\n  0: nofall\n  1: fall\n"
        )
        config = train.TrainingConfig(
            model="yolo26n.pt",
            task="detect",
            data=str(data_yaml),
            classes=["nofall", "fall"],
            imgsz=640,
            epochs=50,
            patience=10,
            seed=42,
            device="",
            project=str(tmp_path),
            name="run",
        )

        train.write_run_manifest(
            run_dir, config, None, effective_epochs=1, effective_device="0"
        )

        manifest = json.loads((run_dir / "run_manifest.json").read_text())
        assert manifest["config"]["epochs"] == 1
        assert manifest["config"]["device"] == "0"
        assert manifest["config_file_defaults"]["epochs"] == 50
        assert manifest["config_file_defaults"]["device"] == ""

    def test_no_best_pt_omits_sha256(self, tmp_path):
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        data_yaml = tmp_path / "fall_training_dataset.yaml"
        dataset_root = tmp_path / "dataset"
        dataset_root.mkdir()
        data_yaml.write_text(
            f"path: {dataset_root}\ntrain: images/train\nval: images/val\n"
            "names:\n  0: nofall\n  1: fall\n"
        )
        config = train.TrainingConfig(
            model="yolo26n.pt",
            task="detect",
            data=str(data_yaml),
            classes=["nofall", "fall"],
            imgsz=640,
            epochs=50,
            patience=10,
            seed=42,
            device="",
            project=str(tmp_path),
            name="run",
        )

        train.write_run_manifest(run_dir, config, None)

        manifest = json.loads((run_dir / "run_manifest.json").read_text())
        assert "best_pt_sha256" not in manifest
