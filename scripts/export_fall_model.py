"""train_fall_detector.py가 만든 best.pt를 배포용 위치로 복사하고 무결성

정보(SHA-256)를 검증한다. run_dir에 Ultralytics가 남긴 results.csv가 있으면
best.pt에 해당하는 epoch(마지막 epoch가 아니라 mAP50-95가 가장 높은 epoch)의
Precision/Recall/mAP도 함께 읽어 기록한다 — 학습 스크립트가 아니라 이
스크립트가 지표를 계산하지는 않는다 (docs/fall_evaluation.md 참고).

Colab에서 학습한 best.pt를 로컬로 내려받은 뒤, 이 스크립트로 배포 경로에
복사하면서 run_manifest.json의 SHA-256과 실제 파일의 SHA-256이 일치하는지
검증한다 — 다운로드/전송 중 손상 여부를 조용히 넘어가지 않기 위함이다.

Usage:
    .venv/bin/python scripts/export_fall_model.py \
        --run-dir outputs/fall_training/runs/fall_detector \
        --dest models/fall_detector_v1.pt
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
from pathlib import Path
from typing import Optional


class ExportError(ValueError):
    """모델 산출물 검증 실패 (사용자가 조치해야 하는 문제)."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--run-dir", required=True, help="train_fall_detector.py의 project/name 출력 디렉터리"
    )
    parser.add_argument("--dest", required=True, help="best.pt를 복사할 배포 경로")
    parser.add_argument(
        "--force", action="store_true", help="--dest에 이미 파일이 있어도 덮어쓴다."
    )
    return parser.parse_args()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


_METRIC_COLUMNS = {
    "metrics/precision(B)": "precision",
    "metrics/recall(B)": "recall",
    "metrics/mAP50(B)": "mAP50",
    "metrics/mAP50-95(B)": "mAP50_95",
}


def _read_best_epoch_metrics(run_dir: Path) -> Optional[dict]:
    """Ultralytics results.csv에서 best.pt에 해당하는 epoch의 지표를 읽는다.

    results.csv가 없으면(학습을 이 스크립트 밖에서 다른 방식으로 만들었거나
    아직 없으면) None을 반환한다 — 지표 없이도 SHA-256 검증·복사는 계속
    진행할 수 있어야 하므로 오류로 처리하지 않는다.

    마지막 행(최종 epoch)이 아니라 `metrics/mAP50-95(B)`가 가장 높은 행을
    쓴다 — patience(early stopping)로 인해 best.pt는 보통 마지막 epoch가
    아닌 더 이른 epoch에서 저장되므로, 마지막 행을 쓰면 실제 best.pt의
    성능과 다른 지표가 기록된다. mAP50-95는 Ultralytics가 체크포인트 선택에
    쓰는 내부 fitness와 정확히 같지는 않지만 가장 가까운 표준 지표라
    근사치로 쓴다. 이 컬럼이 없으면(비표준 results.csv) 마지막 행으로
    fallback한다.
    """
    results_path = run_dir / "results.csv"
    if not results_path.is_file():
        return None

    with open(results_path, "r", encoding="utf-8", newline="") as file:
        rows = [{k.strip(): v for k, v in row.items()} for row in csv.DictReader(file)]
    if not rows:
        return None

    best_column = "metrics/mAP50-95(B)"
    best_row = rows[-1]
    best_value = None
    for row in rows:
        raw = row.get(best_column)
        if raw is None:
            continue
        try:
            value = float(raw)
        except ValueError:
            continue
        if best_value is None or value > best_value:
            best_value = value
            best_row = row

    metrics = {}
    for column, key in _METRIC_COLUMNS.items():
        if column in best_row:
            try:
                metrics[key] = float(best_row[column])
            except ValueError:
                continue
    return metrics or None


def verify_and_export(run_dir: Path, dest: Path, force: bool) -> dict:
    best_pt_path = run_dir / "weights" / "best.pt"
    manifest_path = run_dir / "run_manifest.json"

    if not best_pt_path.is_file():
        raise ExportError(f"best.pt를 찾을 수 없습니다: {best_pt_path}")
    if not manifest_path.is_file():
        raise ExportError(f"run_manifest.json을 찾을 수 없습니다: {manifest_path}")

    with open(manifest_path, "r", encoding="utf-8") as file:
        manifest = json.load(file)

    expected_sha256 = manifest.get("best_pt_sha256")
    actual_sha256 = _sha256(best_pt_path)
    if expected_sha256 is not None and expected_sha256 != actual_sha256:
        raise ExportError(
            f"best.pt의 SHA-256이 run_manifest.json과 다릅니다 "
            f"(기록={expected_sha256}, 실제={actual_sha256}) — 전송 중 손상 가능성."
        )

    if dest.exists() and not force:
        raise ExportError(f"{dest}가 이미 존재합니다 (--force로 덮어쓰기 허용).")
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(best_pt_path, dest)

    return {
        "source": str(best_pt_path),
        "dest": str(dest),
        "sha256": actual_sha256,
        "training_config": manifest.get("config"),
        "best_epoch_metrics": _read_best_epoch_metrics(run_dir),
    }


def main() -> None:
    args = parse_args()
    result = verify_and_export(Path(args.run_dir), Path(args.dest), args.force)
    print(f"내보내기 완료: {result['dest']} (sha256={result['sha256']})")
    if result["best_epoch_metrics"]:
        print(f"best epoch 지표: {result['best_epoch_metrics']}")


if __name__ == "__main__":
    try:
        main()
    except ExportError as exc:
        raise SystemExit(str(exc)) from exc
