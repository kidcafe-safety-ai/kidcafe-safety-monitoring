"""Homography 기반 floor-plane 좌표 변환 (Phase 4 PoC, 기본 비활성).

픽셀 `foot_point`를 meter 단위 floor 좌표로 변환한다. 기존 image-normalized
Zone 판정 경로는 그대로 두고, 이 모듈은 opt-in PoC 경로로만 사용한다.

좌표계 정의·기준점 배치·채택 기준: docs/homography_calibration.md
설계 근거: docs/decisions.md ADR-023
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import List, Sequence

import cv2
import numpy as np

SCHEMA_VERSION = 1
COORDINATE_UNIT = "meter"
MIN_FIT_POINTS = 4

REQUIRED_FIELDS = (
    "schema_version",
    "calibration_version",
    "enabled",
    "camera_id",
    "frame_size",
    "coordinate_unit",
    "origin_description",
    "image_points_px",
    "floor_points",
)

# 좌표 중복·동일 직선 판정 허용 오차. 픽셀·meter 모두에 적용한다.
_DUPLICATE_TOL = 1e-9
_COLLINEAR_TOL = 1e-6
# 투영 결과 w가 0에 가까우면 바닥 평면 밖(수평선 근처)이라 변환할 수 없다.
_PROJECTIVE_TOL = 1e-9
# 역행렬 존재 판정 허용 오차. 행렬식은 좌표 단위(px, meter)에 따라 크기가 달라져
# 절대 임계값으로 쓸 수 없으므로, scale과 무관한 역조건수를 사용한다.
_RECIPROCAL_CONDITION_TOL = 1e-12


class CalibrationError(ValueError):
    """Calibration config가 계약을 만족하지 않음."""


class CalibrationMismatchError(CalibrationError):
    """camera_id 또는 해상도가 실행 중인 입력과 다름 (fail-fast 대상)."""


@dataclass(frozen=True)
class CalibrationConfig:
    """`configs/camera_calibration/<camera_id>.json`의 runtime 표현.

    holdout 기준점은 이 config에 포함하지 않는다. `calibration_points.csv`에서만
    관리한다 (docs/homography_calibration.md 4.3).
    """

    schema_version: int
    calibration_version: str
    enabled: bool
    camera_id: str
    frame_width: int
    frame_height: int
    coordinate_unit: str
    origin_description: str
    image_points_px: List[List[float]]
    floor_points: List[List[float]]


def _require_point_list(value, field: str) -> List[List[float]]:
    """`[[x, y], ...]` 형태이고 모든 좌표가 finite인지 확인."""
    if not isinstance(value, list) or not value:
        raise CalibrationError(f"'{field}' must be a non-empty list of [x, y] pairs")

    points: List[List[float]] = []
    for idx, item in enumerate(value):
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            raise CalibrationError(f"'{field}' #{idx} must be an [x, y] pair")
        try:
            x, y = float(item[0]), float(item[1])
        except (TypeError, ValueError):
            raise CalibrationError(f"'{field}' #{idx} must contain numbers")
        if not (np.isfinite(x) and np.isfinite(y)):
            raise CalibrationError(f"'{field}' #{idx} must be finite: got ({x}, {y})")
        points.append([x, y])

    return points


def _require_unique(points: Sequence[Sequence[float]], field: str) -> None:
    for i in range(len(points)):
        for j in range(i + 1, len(points)):
            dx = abs(points[i][0] - points[j][0])
            dy = abs(points[i][1] - points[j][1])
            if dx <= _DUPLICATE_TOL and dy <= _DUPLICATE_TOL:
                raise CalibrationError(f"'{field}' has duplicate points at #{i} and #{j}")


def _require_not_collinear(points: Sequence[Sequence[float]], field: str) -> None:
    """모든 점이 하나의 직선 위에 놓이면 homography를 구할 수 없다."""
    array = np.asarray(points, dtype=np.float64)
    centered = array - array.mean(axis=0)
    singular_values = np.linalg.svd(centered, compute_uv=False)
    scale = float(singular_values[0])
    if scale <= _DUPLICATE_TOL:
        raise CalibrationError(f"'{field}' points are all identical")
    if float(singular_values[1]) / scale <= _COLLINEAR_TOL:
        raise CalibrationError(f"'{field}' points must not all lie on a single line")


def parse_calibration(data: dict) -> CalibrationConfig:
    """dict를 검증해 `CalibrationConfig`로 변환.

    Validations:
        - 필수 필드 존재
        - `schema_version=1`, `coordinate_unit="meter"`
        - `camera_id`·`calibration_version`·`origin_description` 비어있지 않음
        - `frame_size.width/height` 양의 정수
        - image·floor point 개수 동일, 최소 4개
        - 모든 좌표 finite·중복 없음
        - image point는 프레임 내부
        - image·floor 각각 동일 직선 위에만 놓이지 않음

    Raises:
        CalibrationError: 위 조건을 만족하지 않음
    """
    if not isinstance(data, dict):
        raise CalibrationError("calibration config must be a JSON object")

    for field in REQUIRED_FIELDS:
        if field not in data:
            raise CalibrationError(f"missing required field: '{field}'")

    if data["schema_version"] != SCHEMA_VERSION:
        raise CalibrationError(
            f"unsupported schema_version: {data['schema_version']} (expected {SCHEMA_VERSION})"
        )

    if data["coordinate_unit"] != COORDINATE_UNIT:
        raise CalibrationError(
            f"coordinate_unit must be '{COORDINATE_UNIT}': got '{data['coordinate_unit']}'"
        )

    for field in ("calibration_version", "camera_id", "origin_description"):
        value = data[field]
        if not isinstance(value, str) or not value.strip():
            raise CalibrationError(f"'{field}' must be a non-empty string")

    if not isinstance(data["enabled"], bool):
        raise CalibrationError("'enabled' must be a boolean")

    frame_size = data["frame_size"]
    if not isinstance(frame_size, dict):
        raise CalibrationError("'frame_size' must be an object with width and height")
    for field in ("width", "height"):
        if field not in frame_size:
            raise CalibrationError(f"'frame_size.{field}' is required")
        value = frame_size[field]
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise CalibrationError(f"'frame_size.{field}' must be a positive integer")

    image_points = _require_point_list(data["image_points_px"], "image_points_px")
    floor_points = _require_point_list(data["floor_points"], "floor_points")

    if len(image_points) != len(floor_points):
        raise CalibrationError(
            f"image_points_px ({len(image_points)}) and floor_points "
            f"({len(floor_points)}) must have the same length"
        )
    if len(image_points) < MIN_FIT_POINTS:
        raise CalibrationError(
            f"at least {MIN_FIT_POINTS} fit points are required: got {len(image_points)}"
        )

    width, height = frame_size["width"], frame_size["height"]
    for idx, (x, y) in enumerate(image_points):
        if not (0.0 <= x <= width) or not (0.0 <= y <= height):
            raise CalibrationError(
                f"'image_points_px' #{idx} is outside the frame "
                f"{width}x{height}: got ({x}, {y})"
            )

    _require_unique(image_points, "image_points_px")
    _require_unique(floor_points, "floor_points")
    _require_not_collinear(image_points, "image_points_px")
    _require_not_collinear(floor_points, "floor_points")

    return CalibrationConfig(
        schema_version=data["schema_version"],
        calibration_version=data["calibration_version"],
        enabled=data["enabled"],
        camera_id=data["camera_id"],
        frame_width=width,
        frame_height=height,
        coordinate_unit=data["coordinate_unit"],
        origin_description=data["origin_description"],
        image_points_px=image_points,
        floor_points=floor_points,
    )


def load_calibration(json_path: str) -> CalibrationConfig:
    """Calibration config 파일을 로드해 검증.

    Raises:
        FileNotFoundError: 파일이 없음
        CalibrationError: JSON 형식 오류 또는 계약 위반
    """
    path = Path(json_path)
    if not path.exists():
        raise FileNotFoundError(f"Calibration file not found: {json_path}")

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise CalibrationError(f"Invalid JSON in {json_path}: {e}")

    return parse_calibration(data)


class FloorPlaneTransformer:
    """픽셀 좌표를 meter 단위 floor 좌표로 변환한다.

    fit point 전체와 `cv2.findHomography(..., method=0)`을 사용한다. RANSAC 등
    outlier 제거 방식은 쓰지 않는다. 기준점 수가 적어 모든 점을 그대로 사용하는
    것이 계약이다 (docs/interfaces.md).

    기본적으로 sparse 변환용이다. 매 프레임 전체 픽셀을 변환하지 않고 Event
    시점의 `foot_point`만 변환한다.
    """

    def __init__(self, config: CalibrationConfig):
        self.config = config
        self.matrix = self._fit(config)

    @staticmethod
    def _fit(config: CalibrationConfig) -> np.ndarray:
        image_points = np.asarray(config.image_points_px, dtype=np.float64)
        floor_points = np.asarray(config.floor_points, dtype=np.float64)

        matrix, _ = cv2.findHomography(image_points, floor_points, method=0)
        if matrix is None:
            raise CalibrationError("failed to compute homography from the given fit points")
        if not np.isfinite(matrix).all():
            raise CalibrationError("homography matrix is not finite")

        singular_values = np.linalg.svd(matrix, compute_uv=False)
        largest = float(singular_values[0])
        if largest <= 0.0:
            raise CalibrationError("homography matrix is singular and cannot be inverted")
        if float(singular_values[-1]) / largest <= _RECIPROCAL_CONDITION_TOL:
            raise CalibrationError("homography matrix is singular and cannot be inverted")

        return matrix

    @classmethod
    def from_file(cls, json_path: str) -> "FloorPlaneTransformer":
        return cls(load_calibration(json_path))

    @property
    def enabled(self) -> bool:
        """Config의 opt-in 플래그. 호출자가 PoC 경로 사용 여부를 결정한다."""
        return self.config.enabled

    @property
    def camera_id(self) -> str:
        return self.config.camera_id

    @property
    def calibration_version(self) -> str:
        return self.config.calibration_version

    def verify_source(self, camera_id: str, frame_width: int, frame_height: int) -> None:
        """실행 중인 입력과 calibration이 일치하는지 확인한다.

        camera_id나 해상도가 다르면 기존 image-coordinate 경로로 조용히
        fallback하지 않고 즉시 실패한다 (ADR-023).

        Raises:
            CalibrationMismatchError: camera_id 또는 해상도 불일치
        """
        if camera_id != self.config.camera_id:
            raise CalibrationMismatchError(
                f"camera_id mismatch: calibration '{self.config.camera_id}' "
                f"but source '{camera_id}'"
            )
        if frame_width != self.config.frame_width or frame_height != self.config.frame_height:
            raise CalibrationMismatchError(
                f"frame size mismatch: calibration "
                f"{self.config.frame_width}x{self.config.frame_height} "
                f"but source {frame_width}x{frame_height}"
            )

    def transform(self, point: Sequence[float]) -> List[float]:
        """픽셀 `[x, y]`를 meter `[floor_x, floor_y]`로 변환.

        Raises:
            ValueError: 좌표 형식 오류, finite가 아님, 또는 바닥 평면 밖으로
                투영되어 변환할 수 없음
        """
        if not isinstance(point, (list, tuple, np.ndarray)) or len(point) != 2:
            raise ValueError("point must be an [x, y] pair")

        x, y = float(point[0]), float(point[1])
        if not (np.isfinite(x) and np.isfinite(y)):
            raise ValueError(f"point must be finite: got ({x}, {y})")

        projected = self.matrix @ np.array([x, y, 1.0], dtype=np.float64)
        w = float(projected[2])
        if abs(w) <= _PROJECTIVE_TOL:
            raise ValueError(f"point ({x}, {y}) does not project onto the floor plane")

        return [float(projected[0] / w), float(projected[1] / w)]

    def transform_many(self, points: Sequence[Sequence[float]]) -> List[List[float]]:
        """여러 픽셀 좌표를 한 번에 변환. 순서는 입력과 같다."""
        return [self.transform(point) for point in points]

    def fit_residuals_m(self) -> List[float]:
        """fit point의 잔차(meter). 채택 판정용 오차가 아니라 적합도 확인용이다.

        공식 위치 오차는 holdout 관측으로만 계산한다
        (docs/homography_calibration.md 6절).
        """
        residuals = []
        for image_point, expected in zip(self.config.image_points_px, self.config.floor_points):
            predicted = self.transform(image_point)
            dx = predicted[0] - expected[0]
            dy = predicted[1] - expected[1]
            residuals.append(float(np.hypot(dx, dy)))
        return residuals
