"""Zone polygon 공통 검증 규칙.

floor-plane Zone(meter)과 Phase 4 `PUT /zones`(image-normalized)가 같은 규칙을
쓰도록 분리한다. 좌표 범위만 호출자가 지정한다.

계약: docs/api_contract.md `PUT /zones Phase 4 저장 계약`
"""

from __future__ import annotations

import math
from typing import List, Optional, Sequence, Tuple

from shapely.geometry import LinearRing

MIN_POLYGON_POINTS = 3

# 같은 점으로 볼 허용 오차. meter·정규화 좌표 모두에서 실질적으로 동일 지점이다.
_DUPLICATE_TOL = 1e-9
_AREA_TOL = 1e-12
# 직선 판정 허용 오차. 두 변 사이 sine 값에 적용한다.
_COLLINEAR_TOL = 1e-9


def validate_polygon_points(
    points: Sequence[Sequence[float]],
    *,
    coordinate_range: Optional[Tuple[float, float]] = None,
    label: str = "polygon",
) -> List[List[float]]:
    """Polygon 좌표를 검증하고 `[[x, y], ...]`로 정규화해 반환.

    Validations:
        - `[x, y]` 쌍 목록이고 최소 3개
        - 모든 좌표가 finite (NaN·Infinity 거부)
        - `coordinate_range`가 주어지면 그 범위 안
        - 중복 점 없음
        - open ring — 첫 점을 끝에 반복하지 않음
        - 면적 0 아님
        - self-intersection 없음

    Raises:
        ValueError: 위 조건을 만족하지 않음
    """
    if not isinstance(points, (list, tuple)):
        raise ValueError(f"{label} must be a list of [x, y] pairs")
    if len(points) < MIN_POLYGON_POINTS:
        raise ValueError(
            f"{label} must have at least {MIN_POLYGON_POINTS} points: got {len(points)}"
        )

    parsed: List[List[float]] = []
    for idx, item in enumerate(points):
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            raise ValueError(f"{label} #{idx} must be an [x, y] pair")
        try:
            x, y = float(item[0]), float(item[1])
        except (TypeError, ValueError):
            raise ValueError(f"{label} #{idx} must contain numbers")
        if not (math.isfinite(x) and math.isfinite(y)):
            raise ValueError(f"{label} #{idx} must be finite: got ({x}, {y})")
        if coordinate_range is not None:
            low, high = coordinate_range
            if not (low <= x <= high) or not (low <= y <= high):
                raise ValueError(
                    f"{label} #{idx} out of range [{low}, {high}]: got ({x}, {y})"
                )
        parsed.append([x, y])

    first, last = parsed[0], parsed[-1]
    if _same_point(first, last):
        raise ValueError(f"{label} must be an open ring: the first point must not be repeated")

    for i in range(len(parsed)):
        for j in range(i + 1, len(parsed)):
            if _same_point(parsed[i], parsed[j]):
                raise ValueError(f"{label} has duplicate points at #{i} and #{j}")

    # 순서 주의: 한 직선 위의 점들과 bowtie는 둘 다 LinearRing이 non-simple이고
    # bowtie는 shoelace 면적까지 0이 될 수 있다. 계약 fixture가 요구하는 메시지가
    # 서로 다르므로 collinear → self-intersection → 면적 순으로 판정한다.
    if _is_collinear(parsed):
        raise ValueError(f"{label} must not have zero area")

    if not LinearRing(parsed).is_simple:
        raise ValueError(f"{label} must not self-intersect")

    if _shoelace_area(parsed) <= _AREA_TOL:
        raise ValueError(f"{label} must not have zero area")

    return parsed


def _is_collinear(points: Sequence[Sequence[float]]) -> bool:
    """모든 점이 하나의 직선 위에 있는지 판정. 중복 점은 이미 제외된 상태다."""
    origin = points[0]
    base_x = points[1][0] - origin[0]
    base_y = points[1][1] - origin[1]
    base_len = math.hypot(base_x, base_y)

    for point in points[2:]:
        dx = point[0] - origin[0]
        dy = point[1] - origin[1]
        length = math.hypot(dx, dy)
        cross = abs(base_x * dy - base_y * dx)
        if cross > _COLLINEAR_TOL * base_len * length:
            return False

    return True


def _same_point(a: Sequence[float], b: Sequence[float]) -> bool:
    return abs(a[0] - b[0]) <= _DUPLICATE_TOL and abs(a[1] - b[1]) <= _DUPLICATE_TOL


def _shoelace_area(points: Sequence[Sequence[float]]) -> float:
    """방향과 무관한 polygon 면적."""
    total = 0.0
    count = len(points)
    for i in range(count):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % count]
        total += x1 * y2 - x2 * y1
    return abs(total) / 2.0
