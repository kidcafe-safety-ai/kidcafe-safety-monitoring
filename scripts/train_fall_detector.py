"""configs/fall_training.json 기준으로 yolo26n.pt를 fall/nofall 2-class

detection으로 fine-tuning한다 (자세한 내용은 docs/fall_evaluation.md 참고,
`feature/fall-detector` PR2 안에서 이어지는 세 번째 커밋 단위).

처음부터 학습하지 않고 pretrained yolo26n.pt에서 transfer learning만 수행한다.
학습 자체는 GPU가 필요해 Colab에서 실행하는 것을 전제로 하지만, 이 스크립트는
로컬 CPU 환경에서도 (매우 느리더라도) 동일하게 동작해야 한다 — 데이터 검증과
CLI 로직은 로컬에서 pytest로 확인한다 (tests/test_train_fall_detector.py는
ultralytics 학습 루프 자체는 mocking하고, 설정 로딩·검증·산출물 기록 로직만
검증한다).

산출물 추적을 위해 학습이 끝나면 run 디렉터리에 다음을 함께 남긴다:
    - 사용한 학습 설정(JSON)
    - Ultralytics results.csv(자체 기록)
    - best.pt의 SHA-256
    - 데이터 split manifest(train/val에 실제 사용된 파일 목록)
    - 실행 일자·환경(python/torch/ultralytics 버전)

best.pt, 원본 이미지, runs 디렉터리 전체는 Git에 올리지 않는다
(.gitignore의 outputs/ 참고).

Usage:
    .venv/bin/python scripts/train_fall_detector.py --config configs/fall_training.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class TrainingConfig:
    model: str
    task: str
    data: str
    classes: list
    imgsz: int
    epochs: int
    patience: int
    seed: int
    device: str
    project: str
    name: str

    @classmethod
    def from_file(cls, path: str) -> "TrainingConfig":
        with open(path, "r", encoding="utf-8") as file:
            raw = json.load(file)
        required = {
            "model",
            "task",
            "data",
            "classes",
            "imgsz",
            "epochs",
            "patience",
            "seed",
            "device",
            "project",
            "name",
        }
        missing = required - set(raw)
        if missing:
            raise ValueError(f"{path}에 필수 필드가 없습니다: {sorted(missing)}")
        if raw["classes"] != ["nofall", "fall"]:
            raise ValueError(
                f"classes는 반드시 [\"nofall\", \"fall\"] 순서여야 합니다 "
                f"(fall_training_dataset.yaml의 0: nofall, 1: fall과 일치해야 함): "
                f"{raw['classes']}"
            )
        return cls(**{k: raw[k] for k in required})


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--config", default="configs/fall_training.json")
    parser.add_argument(
        "--epochs", type=int, default=None, help="설정 파일의 epochs를 재정의한다."
    )
    parser.add_argument(
        "--device",
        default=None,
        help=(
            "설정 파일의 device를 재정의한다. 빈 문자열(기본값)은 Ultralytics가 "
            "자동 선택한다. Colab GPU에서는 명시적으로 0(예: --device 0)을 준다."
        ),
    )
    return parser.parse_args()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _collect_split_manifest(data_yaml_path: Path) -> dict:
    """data.yaml이 가리키는 images/{train,val} 디렉터리의 파일 목록을 기록한다.

    나중에 "이 모델이 정확히 어떤 프레임으로 학습됐는지" 재현·감사할 수 있게
    하기 위함이다 (Subject 분할 실수로 인한 데이터 누수를 사후에도 검증 가능).
    """
    import yaml

    with open(data_yaml_path, "r", encoding="utf-8") as file:
        data_cfg = yaml.safe_load(file)

    dataset_root = Path(data_cfg["path"])
    if not dataset_root.is_absolute():
        dataset_root = data_yaml_path.parent.parent / dataset_root

    manifest = {}
    for split in ("train", "val"):
        images_dir = dataset_root / data_cfg[split]
        if images_dir.is_dir():
            manifest[split] = sorted(p.name for p in images_dir.glob("*.png"))
        else:
            manifest[split] = []
    return manifest


def run_training(
    config: TrainingConfig,
    epochs_override: Optional[int],
    device_override: Optional[str],
):
    """ultralytics.YOLO를 이용해 실제 학습을 수행한다.

    ultralytics import를 함수 안으로 미룬다 — 이 모듈은 학습을 실행하지 않는
    호출자(테스트, --help 등)에서 무거운 torch/ultralytics 의존성을 강제로
    불러오지 않기 위함이다.

    체크포인트 재개(resume) 기능은 제공하지 않는다 — `YOLO(config.model)`이
    항상 pretrained 가중치에서 새로 시작하므로, resume=True를 그대로
    전달해도 실제로 중단된 학습을 이어가지 않는다(마지막 run의 last.pt를
    명시적으로 다시 로드해야 하는데 이 스크립트는 그렇게 하지 않는다). 필요
    해지면 마지막 run 디렉터리를 찾아 `YOLO(last.pt)`로 다시 로드하는 로직을
    별도로 구현해야 한다.
    """
    from ultralytics import YOLO

    epochs = epochs_override if epochs_override is not None else config.epochs
    device = device_override if device_override is not None else config.device
    # project는 절대경로로 변환해 전달한다 — 상대경로를 그대로 넘기면
    # Ultralytics가 호출 시점의 cwd 기준으로 해석해, 실행 위치에 따라(예: Colab
    # 노트북 cwd가 스크립트 실행 스크립트와 다를 때) run 디렉터리가 예상과
    # 다른 곳에 생길 수 있다.
    project = str(Path(config.project).resolve())

    model = YOLO(config.model)
    results = model.train(
        data=config.data,
        imgsz=config.imgsz,
        epochs=epochs,
        patience=config.patience,
        seed=config.seed,
        device=device,
        project=project,
        name=config.name,
    )
    return model, results, epochs, device


def write_run_manifest(
    run_dir: Path,
    config: TrainingConfig,
    best_pt_path: Optional[Path],
    effective_epochs: Optional[int] = None,
    effective_device: Optional[str] = None,
) -> None:
    """run_manifest.json에 실제로 학습에 쓰인 값을 기록한다.

    effective_epochs/effective_device를 생략하면 config 파일의 원본 값을
    그대로 쓴다 — CLI(--epochs/--device)로 재정의한 값이 config 파일 값과
    다를 수 있으므로, main()에서 실제 실행에 쓰인 값을 넘겨야 재현 가능한
    기록이 된다.
    """
    manifest = {
        "config": {
            "model": config.model,
            "task": config.task,
            "data": config.data,
            "classes": config.classes,
            "imgsz": config.imgsz,
            "epochs": effective_epochs if effective_epochs is not None else config.epochs,
            "patience": config.patience,
            "seed": config.seed,
            "device": effective_device if effective_device is not None else config.device,
        },
        "config_file_defaults": {
            "epochs": config.epochs,
            "device": config.device,
        },
        "run_at_utc": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "python": sys.version,
            "platform": platform.platform(),
        },
        "split_manifest": _collect_split_manifest(Path(config.data)),
    }
    try:
        import torch

        manifest["environment"]["torch"] = torch.__version__
    except ImportError:
        pass
    try:
        import ultralytics

        manifest["environment"]["ultralytics"] = ultralytics.__version__
    except ImportError:
        pass

    if best_pt_path is not None and best_pt_path.is_file():
        manifest["best_pt_sha256"] = _sha256(best_pt_path)
        manifest["best_pt_path"] = str(best_pt_path)

    manifest_path = run_dir / "run_manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as file:
        json.dump(manifest, file, ensure_ascii=False, indent=2)
    print(f"run manifest 저장: {manifest_path}")


def main() -> None:
    args = parse_args()
    config = TrainingConfig.from_file(args.config)

    print(
        f"학습 시작: model={config.model} "
        f"epochs={args.epochs or config.epochs} device={args.device or config.device}"
    )
    model, results, effective_epochs, effective_device = run_training(
        config, args.epochs, args.device
    )

    if hasattr(results, "save_dir"):
        run_dir = Path(results.save_dir)
    else:
        run_dir = Path(config.project).resolve() / config.name
    best_pt_path = run_dir / "weights" / "best.pt"
    write_run_manifest(
        run_dir,
        config,
        best_pt_path if best_pt_path.is_file() else None,
        effective_epochs=effective_epochs,
        effective_device=effective_device,
    )


if __name__ == "__main__":
    main()
