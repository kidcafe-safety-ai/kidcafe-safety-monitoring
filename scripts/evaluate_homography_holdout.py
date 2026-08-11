"""클립별 calibration의 holdout 위치 오차를 교차검증으로 측정한다.

8월 7일 촬영에서 확보한 기준점은 10개다. `homography_acceptance_v1`은 holdout
10위치·20관측을 요구하는데, fit 점을 고정하면 남은 점만 holdout이 되어 요구를
만족할 수 없다. 그래서 점마다 하나씩 빼고 나머지로 fit해 모든 점이 한 번씩
holdout이 되게 한다.

fit 점 수는 `--fit-mode`로 고른다. 계약이 fit 기준점을 "최소 4개"로만 정하고
상한을 두지 않으므로 남은 점을 모두 쓰는 최소자승(`all`, 기본값)이 계약 안에
있다. 4점만 쓰면(`quad`) fit 사각형 밖이 전부 외삽이 되어, 측정값이 변환 성능이
아니라 어떤 4점을 골랐는지를 반영하게 된다. 같은 입력에서 p95가 2.89와 8.56으로
갈릴 만큼 차이가 크므로 기본값을 `all`로 둔다.

내삽·외삽은 그 fit 점들의 볼록껍질 안팎으로 나눠 따로 보고한다. 껍질 밖 오차는
변환 정확도와 기준점 배치 한계가 섞인 값이라 합산 수치만으로는 원인을 가릴 수
없다.

촬영 중 카메라가 고정되지 않아 단일 calibration을 전 클립에 쓸 수 없다. 클립마다
`pick_calibration_points.py`로 만든 클릭 결과를 넣으면 클립별 결과와 합산 결과를
함께 낸다.

사용 예:

    python scripts/evaluate_homography_holdout.py \\
        --points docs/calibration_points.csv \\
        --picked configs/camera_calibration/cam01_clip00_orig_picked.csv \\
        --picked configs/camera_calibration/cam01_clip01_picked.csv \\
        --unit-cm 1 \\
        --output outputs/homography/holdout_eval.json
"""

from __future__ import annotations

import argparse
import csv
import itertools
import json
import math
import os
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.geofencing.homography_evaluation import (  # noqa: E402
    summarize_errors_m,
)

FIT_POINT_COUNT = 4
PICKED_FIELDS = ("point_id", "role", "pixel_x", "pixel_y")


class HoldoutEvalError(ValueError):
    """입력이 평가 계약을 만족하지 않음."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--points", required=True, help="실측 좌표 CSV (point_id,role,y,x)")
    parser.add_argument(
        "--picked",
        action="append",
        required=True,
        help="클립별 클릭 결과 CSV. 여러 번 지정한다.",
    )
    parser.add_argument("--unit-cm", type=float, required=True)
    parser.add_argument(
        "--fit-mode",
        choices=("all", "quad"),
        default="all",
        help="all=대상 점을 뺀 전부로 최소자승, quad=최대 면적 4점만.",
    )
    parser.add_argument("--output", required=True)
    return parser.parse_args()


def load_floor_points(path: Path, unit_cm: float) -> Dict[str, Tuple[float, float]]:
    """실측 CSV를 `{point_id: (x_m, y_m)}`로 읽는다."""
    if not math.isfinite(unit_cm) or unit_cm <= 0:
        raise HoldoutEvalError("--unit-cm은 0보다 큰 유한한 값이어야 합니다.")
    if not path.is_file():
        raise HoldoutEvalError(f"실측 좌표 CSV가 없습니다: {path}")
    result: Dict[str, Tuple[float, float]] = {}
    with open(path, "r", encoding="utf-8", newline="") as file:
        for number, row in enumerate(csv.DictReader(file), start=2):
            point_id = (row.get("point_id") or "").strip()
            if not point_id or point_id in result:
                raise HoldoutEvalError(f"{number}행 point_id가 비었거나 중복입니다.")
            try:
                y_raw = float(row["y"])
                x_raw = float(row["x"])
            except (KeyError, TypeError, ValueError) as exc:
                raise HoldoutEvalError(f"{number}행 좌표를 읽을 수 없습니다.") from exc
            if not (math.isfinite(y_raw) and math.isfinite(x_raw)):
                raise HoldoutEvalError(f"{number}행 좌표가 유한하지 않습니다.")
            result[point_id] = (x_raw * unit_cm / 100.0, y_raw * unit_cm / 100.0)
    if len(result) < FIT_POINT_COUNT + 1:
        raise HoldoutEvalError(
            f"기준점이 {FIT_POINT_COUNT + 1}개 이상이어야 교차검증할 수 있습니다."
        )
    return result


def load_picked(path: Path, expected: Sequence[str]) -> Dict[str, Tuple[float, float]]:
    """클립 하나의 클릭 결과를 `{point_id: (px, py)}`로 읽는다."""
    if not path.is_file():
        raise HoldoutEvalError(f"클릭 결과 CSV가 없습니다: {path}")
    result: Dict[str, Tuple[float, float]] = {}
    with open(path, "r", encoding="utf-8", newline="") as file:
        reader = csv.DictReader(file)
        missing = {"point_id", "pixel_x", "pixel_y"} - set(reader.fieldnames or [])
        if missing:
            raise HoldoutEvalError(f"{path} 필수 컬럼이 없습니다: {sorted(missing)}")
        for number, row in enumerate(reader, start=2):
            point_id = (row.get("point_id") or "").strip()
            if point_id in result:
                raise HoldoutEvalError(f"{path} {number}행 point_id가 중복입니다.")
            try:
                result[point_id] = (float(row["pixel_x"]), float(row["pixel_y"]))
            except (TypeError, ValueError) as exc:
                raise HoldoutEvalError(f"{path} {number}행 픽셀 좌표 오류") from exc
    unmatched = set(expected) - set(result)
    if unmatched:
        raise HoldoutEvalError(f"{path}에 없는 기준점: {sorted(unmatched)}")
    return result


def _quad_area(points: Sequence[Tuple[float, float]]) -> float:
    """네 점을 볼록 순서로 정렬한 뒤 신발끈 공식으로 면적을 낸다."""
    center_x = sum(p[0] for p in points) / len(points)
    center_y = sum(p[1] for p in points) / len(points)
    ordered = sorted(points, key=lambda p: math.atan2(p[1] - center_y, p[0] - center_x))
    total = 0.0
    for index in range(len(ordered)):
        x1, y1 = ordered[index]
        x2, y2 = ordered[(index + 1) % len(ordered)]
        total += x1 * y2 - x2 * y1
    return abs(total) / 2.0


def choose_fit_sets(
    floor: Dict[str, Tuple[float, float]], mode: str
) -> Dict[str, Tuple[str, ...]]:
    """점마다 holdout으로 뺄 대상을 정하고 나머지를 fit으로 쓴다.

    `homography_acceptance_v1`은 fit 기준점을 "최소 4개"로 정한다. 상한이 없으므로
    남은 점을 모두 쓰는 최소자승 추정이 계약 안에 있다. 4점만 쓰면 fit 사각형
    밖이 전부 외삽이 되어 오차가 변환 성능이 아니라 조합 선택의 결과가 된다.

    - `all`: 대상 점을 제외한 전부를 fit으로 쓴다 (기본값).
    - `quad`: 대상 점을 제외한 조합 중 사각형 면적이 최대인 4점만 쓴다. 기준점이
      4개뿐인 촬영과 비교하기 위해 남겨둔 경로다.

    두 규칙 모두 오차를 보기 전에 정해지므로 사후 선택 여지가 없다.
    """
    ids = sorted(floor)
    chosen: Dict[str, Tuple[str, ...]] = {}
    for target in ids:
        others = tuple(i for i in ids if i != target)
        if mode == "all":
            chosen[target] = others
            continue
        best: Tuple[float, Tuple[str, ...]] | None = None
        for combo in itertools.combinations(others, FIT_POINT_COUNT):
            area = _quad_area([floor[i] for i in combo])
            if best is None or area > best[0]:
                best = (area, combo)
        if best is None or best[0] <= 0.0:
            raise HoldoutEvalError(f"{target}을 뺀 유효한 fit 조합이 없습니다.")
        chosen[target] = best[1]
    return chosen


def fit_homography(src: np.ndarray, dst: np.ndarray) -> np.ndarray:
    """fit 점이 4개면 정확해, 그보다 많으면 최소자승으로 homography를 구한다.

    `findHomography(method=0)`은 RANSAC 없이 전체 대응을 최소자승으로 푼다.
    기준점을 사람이 직접 확인해 찍었으므로 이상치 제거는 필요하지 않고, 오히려
    RANSAC이 일부 점을 버리면 결과가 실행마다 달라진다.
    """
    if len(src) == FIT_POINT_COUNT:
        return cv2.getPerspectiveTransform(src, dst)
    matrix, _ = cv2.findHomography(src, dst, 0)
    if matrix is None:
        raise HoldoutEvalError("homography를 추정하지 못했습니다.")
    return matrix


def _inside(polygon: np.ndarray, point: Tuple[float, float]) -> bool:
    """fit 4점의 볼록껍질 안이면 내삽, 밖이면 외삽이다."""
    hull = cv2.convexHull(polygon.astype(np.float32))
    return cv2.pointPolygonTest(hull, (float(point[0]), float(point[1])), False) >= 0


def evaluate(
    floor: Dict[str, Tuple[float, float]],
    clips: Dict[str, Dict[str, Tuple[float, float]]],
    fit_sets: Dict[str, Tuple[str, ...]],
) -> List[dict]:
    observations: List[dict] = []
    for clip_name in sorted(clips):
        picked = clips[clip_name]
        for target in sorted(floor):
            fit = fit_sets[target]
            src = np.float32([picked[i] for i in fit])
            dst = np.float32([floor[i] for i in fit])
            matrix = fit_homography(src, dst)
            vector = matrix @ np.array([*picked[target], 1.0])
            if not math.isfinite(vector[2]) or abs(vector[2]) < 1e-12:
                raise HoldoutEvalError(f"{clip_name}/{target} 투영이 발산했습니다.")
            got = (float(vector[0] / vector[2]), float(vector[1] / vector[2]))
            expected = floor[target]
            observations.append(
                {
                    "clip": clip_name,
                    "point_id": target,
                    "fit_points": list(fit),
                    "expected_m": list(expected),
                    "predicted_m": list(got),
                    "error_m": float(math.dist(got, expected)),
                    "region": "interpolation" if _inside(dst, expected) else "extrapolation",
                }
            )
    return observations


def summarize(observations: Sequence[dict], region: str | None = None) -> dict:
    subset = [o for o in observations if region is None or o["region"] == region]
    errors = [o["error_m"] for o in subset]
    if not errors:
        return {"observation_count": 0, "position_count": 0}
    # 평균·p95는 계약 정의를 그대로 쓴다. 여기서 따로 계산하면 판정과 어긋난다.
    mean_m, p95_m = summarize_errors_m(errors)
    return {
        "observation_count": len(errors),
        "position_count": len({o["point_id"] for o in subset}),
        "point_ids": sorted({o["point_id"] for o in subset}),
        "mean_m": mean_m,
        "p95_m": p95_m,
        "max_m": float(max(errors)),
    }


def write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as file:
            json.dump(payload, file, ensure_ascii=False, indent=2)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(temp_name, path)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise


def main() -> None:
    args = parse_args()
    try:
        floor = load_floor_points(Path(args.points), args.unit_cm)
        clips = {
            Path(p).stem: load_picked(Path(p), list(floor)) for p in args.picked
        }
        fit_sets = choose_fit_sets(floor, args.fit_mode)
        observations = evaluate(floor, clips, fit_sets)
    except HoldoutEvalError as exc:
        raise SystemExit(str(exc)) from exc

    payload = {
        "unit_cm": args.unit_cm,
        "clip_count": len(clips),
        "clips": sorted(clips),
        "fit_mode": args.fit_mode,
        "fit_selection_rule": (
            "target 점을 제외한 전부로 최소자승"
            if args.fit_mode == "all"
            else "target 점을 제외한 조합 중 사각형 면적 최대인 4점"
        ),
        "overall": summarize(observations),
        "interpolation": summarize(observations, "interpolation"),
        "extrapolation": summarize(observations, "extrapolation"),
        "per_clip": {
            name: summarize([o for o in observations if o["clip"] == name])
            for name in sorted(clips)
        },
        "observations": observations,
    }
    write_json_atomic(Path(args.output), payload)

    for label, key in (("전체", "overall"), ("내삽", "interpolation"), ("외삽", "extrapolation")):
        stats = payload[key]
        if not stats.get("observation_count"):
            continue
        print(
            f"{label}: {stats['position_count']}위치 / {stats['observation_count']}관측  "
            f"평균 {stats['mean_m'] * 100:.2f}cm  p95 {stats['p95_m'] * 100:.2f}cm  "
            f"최대 {stats['max_m'] * 100:.2f}cm"
        )
    print(f"-> {args.output}")


if __name__ == "__main__":
    main()
