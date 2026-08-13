"""Calibration 기준점의 픽셀 좌표를 영상에서 클릭해 기록한다.

8월 7일 촬영본은 압축 재인코딩본이라 바닥 테이프가 5~15px로 뭉개져 자동
검출이 그림자·나뭇결과 구분되지 않는다. 기준점 픽셀 좌표는 사람이 직접
찍고, 이 스크립트는 그 입력을 계약 형식으로 저장하는 역할만 한다.

촬영 중 카메라가 고정되지 않았으므로(클립 간 최대 8.5도 회전) 클립마다 따로
실행해 클립별 calibration을 만든다. `--frame`으로 어느 프레임을 쓸지 정한다.

실측 floor 좌표는 CSV로 미리 준비한다. 헤더는 `point_id,role,y,x`이고
`role`은 `fit` 또는 `holdout`이다. 클릭 순서는 CSV 행 순서를 따른다.

사용 예:

    python scripts/pick_calibration_points.py \\
        --video data/videos/P4_S01_calibration_cam01.mp4 \\
        --points docs/calibration_points.csv \\
        --camera-id cam01 \\
        --calibration-version 2026-08-07-clip01 \\
        --unit-cm 10 \\
        --output configs/camera_calibration/cam01.json

조작:
    좌클릭      현재 기준점 위치 지정
    마우스 휠   확대·축소
    u, BS       직전 입력 취소
    s, Enter    저장 후 종료
    q / ESC     저장하지 않고 종료
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import List

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.geofencing.floor_plane import (  # noqa: E402
    COORDINATE_UNIT,
    MIN_FIT_POINTS,
    SCHEMA_VERSION,
    parse_calibration,
)

WINDOW = "calibration points"
ZOOM_MIN = 1.0
ZOOM_MAX = 12.0
CSV_FIELDS = ("point_id", "role", "y", "x")
ROLES = ("fit", "holdout")
# 한글 입력 상태·Caps Lock에서도 조작되도록 대소문자와 대체 키를 함께 받는다.
SAVE_KEYS = {ord("s"), ord("S"), 13, 10, 32}
UNDO_KEYS = {ord("u"), ord("U"), 8}
QUIT_KEYS = {ord("q"), ord("Q"), 27}


class PickerError(ValueError):
    """입력 파일이나 조작 결과가 계약을 만족하지 않음."""


@dataclass(frozen=True)
class ReferencePoint:
    """실측 기준점 하나. `floor_x`·`floor_y`는 meter로 변환된 값이다."""

    point_id: str
    role: str
    floor_x: float
    floor_y: float


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", required=True, help="calibration 영상 경로")
    parser.add_argument("--frame", type=int, default=0, help="사용할 프레임 번호")
    parser.add_argument("--points", required=True, help="실측 좌표 CSV")
    parser.add_argument("--camera-id", required=True)
    parser.add_argument("--calibration-version", required=True)
    parser.add_argument(
        "--unit-cm",
        type=float,
        required=True,
        help="CSV의 좌표 1단위가 몇 cm인지. 줄자를 cm로 읽었으면 1.",
    )
    parser.add_argument(
        "--origin-description",
        default="촬영 구역 좌하단 회색 테이프. x는 오른쪽, y는 카메라에서 멀어지는 방향.",
        help="floor 좌표 원점 설명. 비워 둘 수 없다.",
    )
    parser.add_argument("--output", required=True, help="calibration JSON 저장 경로")
    parser.add_argument(
        "--holdout-output",
        default=None,
        help="holdout 픽셀 좌표 CSV 저장 경로. 생략하면 output 옆에 만든다.",
    )
    return parser.parse_args()


def load_reference_points(path: Path, unit_cm: float) -> List[ReferencePoint]:
    """실측 CSV를 읽어 meter 단위 기준점 목록으로 바꾼다.

    CSV는 촬영 현장 기록 순서를 그대로 유지한다. 클릭 순서가 이 순서를 따르므로
    행을 재정렬하면 대응이 어긋난다.
    """
    if not math_is_positive(unit_cm):
        raise PickerError("--unit-cm은 0보다 큰 유한한 값이어야 합니다.")
    if not path.is_file():
        raise PickerError(f"실측 좌표 CSV가 없습니다: {path}")

    with open(path, "r", encoding="utf-8", newline="") as file:
        reader = csv.DictReader(file)
        missing = set(CSV_FIELDS) - set(reader.fieldnames or [])
        if missing:
            raise PickerError(f"CSV 필수 컬럼이 없습니다: {sorted(missing)}")
        rows = list(reader)

    points: List[ReferencePoint] = []
    seen = set()
    for number, row in enumerate(rows, start=2):
        point_id = (row.get("point_id") or "").strip()
        role = (row.get("role") or "").strip()
        if not point_id or point_id in seen:
            raise PickerError(f"{number}행 point_id가 비었거나 중복입니다: {point_id!r}")
        if role not in ROLES:
            raise PickerError(f"{number}행 role은 fit 또는 holdout이어야 합니다: {role!r}")
        seen.add(point_id)
        try:
            y_raw = float(row["y"])
            x_raw = float(row["x"])
        except (TypeError, ValueError) as exc:
            raise PickerError(f"{number}행 좌표를 숫자로 읽을 수 없습니다.") from exc
        if not (math_is_finite(y_raw) and math_is_finite(x_raw)):
            raise PickerError(f"{number}행 좌표가 유한하지 않습니다.")
        # CSV는 현장 기록 그대로 (y, x) 순서이고 단위는 --unit-cm으로 받는다.
        # 내부 표현은 계약대로 meter·(x, y)로 통일한다.
        points.append(
            ReferencePoint(
                point_id=point_id,
                role=role,
                floor_x=x_raw * unit_cm / 100.0,
                floor_y=y_raw * unit_cm / 100.0,
            )
        )

    fit_count = sum(1 for point in points if point.role == "fit")
    if fit_count < MIN_FIT_POINTS:
        raise PickerError(f"fit 기준점이 {MIN_FIT_POINTS}개 이상이어야 합니다: {fit_count}개")
    return points


def math_is_finite(value: float) -> bool:
    return value == value and value not in (float("inf"), float("-inf"))


def math_is_positive(value: float) -> bool:
    return math_is_finite(value) and value > 0


def read_frame(video_path: Path, frame_number: int) -> np.ndarray:
    if not video_path.is_file():
        raise PickerError(f"영상 파일이 없습니다: {video_path}")
    capture = cv2.VideoCapture(str(video_path))
    try:
        total = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        if frame_number < 0 or (total > 0 and frame_number >= total):
            raise PickerError(f"프레임 번호가 범위를 벗어납니다: {frame_number} (총 {total})")
        capture.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
        ok, frame = capture.read()
    finally:
        capture.release()
    if not ok or frame is None:
        raise PickerError(f"프레임을 읽을 수 없습니다: {video_path}#{frame_number}")
    return frame


class Picker:
    """확대 상태를 유지하면서 클릭 좌표를 원본 픽셀로 되돌린다."""

    def __init__(self, frame: np.ndarray, points: List[ReferencePoint]):
        self.frame = frame
        self.points = points
        self.picked: List[List[float]] = []
        self.zoom = 1.0
        self.center = [frame.shape[1] / 2.0, frame.shape[0] / 2.0]
        self.view_size = (min(1600, frame.shape[1]), min(900, frame.shape[0]))

    def to_source(self, view_x: float, view_y: float) -> List[float]:
        vw, vh = self.view_size
        src_x = self.center[0] + (view_x - vw / 2.0) / self.zoom
        src_y = self.center[1] + (view_y - vh / 2.0) / self.zoom
        return [
            float(np.clip(src_x, 0, self.frame.shape[1] - 1)),
            float(np.clip(src_y, 0, self.frame.shape[0] - 1)),
        ]

    def to_view(self, src_x: float, src_y: float) -> tuple:
        vw, vh = self.view_size
        return (
            int(round((src_x - self.center[0]) * self.zoom + vw / 2.0)),
            int(round((src_y - self.center[1]) * self.zoom + vh / 2.0)),
        )

    def render(self) -> np.ndarray:
        vw, vh = self.view_size
        scale = 1.0 / self.zoom
        map_x, map_y = np.meshgrid(
            np.linspace(
                self.center[0] - vw * scale / 2.0, self.center[0] + vw * scale / 2.0, vw
            ).astype(np.float32),
            np.linspace(
                self.center[1] - vh * scale / 2.0, self.center[1] + vh * scale / 2.0, vh
            ).astype(np.float32),
        )
        view = cv2.remap(
            self.frame, map_x, map_y, cv2.INTER_CUBIC, borderMode=cv2.BORDER_CONSTANT
        )

        for index, (src_x, src_y) in enumerate(self.picked):
            point = self.points[index]
            color = (0, 220, 0) if point.role == "fit" else (0, 200, 255)
            position = self.to_view(src_x, src_y)
            cv2.drawMarker(view, position, color, cv2.MARKER_CROSS, 18, 2)
            cv2.putText(
                view,
                point.point_id,
                (position[0] + 10, position[1] - 8),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                color,
                2,
            )

        if len(self.picked) < len(self.points):
            nxt = self.points[len(self.picked)]
            banner = (
                f"[{len(self.picked) + 1}/{len(self.points)}] {nxt.point_id} "
                f"({nxt.role})  floor=({nxt.floor_x:.3f}, {nxt.floor_y:.3f}) m"
            )
        else:
            banner = "모든 점 입력 완료 — s 또는 Enter 저장 / u 취소"
        cv2.rectangle(view, (0, 0), (vw, 34), (0, 0, 0), -1)
        cv2.putText(
            view, banner, (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2
        )
        cv2.putText(
            view,
            f"zoom x{self.zoom:.1f}",
            (vw - 150, 24),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (180, 180, 180),
            1,
        )
        return view

    def on_mouse(self, event, x, y, flags, _param) -> None:
        if event == cv2.EVENT_LBUTTONDOWN and len(self.picked) < len(self.points):
            self.picked.append(self.to_source(x, y))
        elif event == cv2.EVENT_MOUSEWHEEL:
            anchor = self.to_source(x, y)
            step = 1.25 if flags > 0 else 1 / 1.25
            self.zoom = float(np.clip(self.zoom * step, ZOOM_MIN, ZOOM_MAX))
            # 휠을 올린 지점이 화면에서 움직이지 않도록 중심을 다시 맞춘다.
            vw, vh = self.view_size
            self.center = [
                anchor[0] - (x - vw / 2.0) / self.zoom,
                anchor[1] - (y - vh / 2.0) / self.zoom,
            ]

    def run(self) -> bool:
        cv2.namedWindow(WINDOW, cv2.WINDOW_AUTOSIZE)
        cv2.setMouseCallback(WINDOW, self.on_mouse)
        try:
            while True:
                cv2.imshow(WINDOW, self.render())
                key = cv2.waitKey(20) & 0xFF
                if key == 255:
                    continue
                # 한글 입력 상태나 Caps Lock에서도 동작해야 한다. 대소문자와
                # Enter·Space를 모두 저장 키로 받는다.
                if key in QUIT_KEYS:
                    return False
                if key in UNDO_KEYS and self.picked:
                    self.picked.pop()
                if key in SAVE_KEYS:
                    if len(self.picked) != len(self.points):
                        print(
                            f"아직 {len(self.points) - len(self.picked)}개 남았습니다.",
                            file=sys.stderr,
                        )
                        continue
                    return True
        finally:
            cv2.destroyWindow(WINDOW)


def write_json_atomic(path: Path, payload: dict) -> None:
    """부분 기록된 calibration이 남지 않도록 임시 파일에 쓰고 교체한다."""
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


def build_payload(
    args: argparse.Namespace,
    frame: np.ndarray,
    points: List[ReferencePoint],
    picked: List[List[float]],
) -> dict:
    fit = [
        (point, pixel)
        for point, pixel in zip(points, picked)
        if point.role == "fit"
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "calibration_version": args.calibration_version,
        "enabled": False,
        "camera_id": args.camera_id,
        "frame_size": {"width": int(frame.shape[1]), "height": int(frame.shape[0])},
        "coordinate_unit": COORDINATE_UNIT,
        "origin_description": args.origin_description,
        "image_points_px": [pixel for _, pixel in fit],
        "floor_points": [[point.floor_x, point.floor_y] for point, _ in fit],
    }


def write_holdout_csv(
    path: Path, points: List[ReferencePoint], picked: List[List[float]]
) -> int:
    """holdout 점의 픽셀·실측 좌표를 오차 계산용으로 남긴다."""
    rows = [
        {
            "point_id": point.point_id,
            "pixel_x": f"{pixel[0]:.3f}",
            "pixel_y": f"{pixel[1]:.3f}",
            "floor_x_m": f"{point.floor_x:.4f}",
            "floor_y_m": f"{point.floor_y:.4f}",
        }
        for point, pixel in zip(points, picked)
        if point.role == "holdout"
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=("point_id", "pixel_x", "pixel_y", "floor_x_m", "floor_y_m"),
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def check_metadata(args: argparse.Namespace) -> None:
    """클릭을 시작하기 전에 점 좌표와 무관한 필드를 먼저 검증한다.

    클릭 10번은 되돌리기 비싼 작업이라, 설정 오타 때문에 입력이 통째로
    버려지면 안 된다. 점과 무관한 계약 위반은 GUI를 열기 전에 걸러낸다.
    """
    for name in ("camera_id", "calibration_version", "origin_description"):
        if not str(getattr(args, name) or "").strip():
            raise PickerError(f"--{name.replace('_', '-')}는 비워 둘 수 없습니다.")


def write_recovery(path: Path, points: List[ReferencePoint], picked: List[List[float]]) -> None:
    """검증에 실패해도 클릭 결과는 남긴다."""
    rows = [
        {"point_id": point.point_id, "role": point.role,
         "pixel_x": f"{pixel[0]:.3f}", "pixel_y": f"{pixel[1]:.3f}"}
        for point, pixel in zip(points, picked)
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(
            file, fieldnames=("point_id", "role", "pixel_x", "pixel_y"), lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    args = parse_args()
    output = Path(args.output)
    try:
        check_metadata(args)
        points = load_reference_points(Path(args.points), args.unit_cm)
        frame = read_frame(Path(args.video), args.frame)
    except PickerError as exc:
        raise SystemExit(str(exc)) from exc

    picker = Picker(frame, points)
    if not picker.run():
        raise SystemExit("저장하지 않고 종료했습니다.")

    recovery = output.with_name(f"{output.stem}_picked.csv")
    write_recovery(recovery, points, picker.picked)

    payload = build_payload(args, frame, points, picker.picked)
    try:
        # 저장 전에 로더로 검증한다. 4점이 일직선이거나 중복이면 여기서 걸린다.
        parse_calibration(payload)
    except Exception as exc:  # noqa: BLE001 - 로더가 던지는 계약 오류를 그대로 보여준다
        raise SystemExit(
            f"calibration이 계약을 만족하지 않습니다: {exc}\n"
            f"클릭한 좌표는 {recovery}에 저장했습니다."
        ) from exc

    write_json_atomic(output, payload)
    holdout_path = (
        Path(args.holdout_output)
        if args.holdout_output
        else output.with_name(f"{output.stem}_holdout.csv")
    )
    holdout_count = write_holdout_csv(holdout_path, points, picker.picked)

    print(f"calibration 저장: {output} (fit {len(payload['image_points_px'])}점)")
    print(f"holdout 저장: {holdout_path} ({holdout_count}점)")


if __name__ == "__main__":
    main()
