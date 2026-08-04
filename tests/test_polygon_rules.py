"""Zone polygon 공통 검증 규칙 테스트 (Phase 4).

floor-plane Zone과 `PUT /zones`가 함께 사용하는 규칙이라 좌표 범위 유무 양쪽을
모두 확인한다.
"""

import pytest

from src.geofencing.polygon_rules import validate_polygon_points

SQUARE = [[0.1, 0.2], [0.3, 0.2], [0.3, 0.5], [0.1, 0.5]]
NORMALIZED = (0.0, 1.0)


def test_valid_square_is_returned_as_floats():
    result = validate_polygon_points(SQUARE, coordinate_range=NORMALIZED)

    assert result == SQUARE
    assert all(isinstance(v, float) for point in result for v in point)


def test_triangle_is_valid():
    validate_polygon_points([[0.1, 0.2], [0.3, 0.2], [0.3, 0.5]], coordinate_range=NORMALIZED)


def test_fewer_than_three_points_rejected():
    with pytest.raises(ValueError, match="at least 3 points"):
        validate_polygon_points([[0.0, 0.0], [1.0, 1.0]])


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_coordinate_rejected(bad):
    points = [[0.1, 0.2], [bad, 0.2], [0.3, 0.5]]

    with pytest.raises(ValueError, match="finite"):
        validate_polygon_points(points)


def test_closed_ring_rejected():
    """첫 점을 끝에 반복한 closed ring은 저장 형식이 아니다."""
    closed = SQUARE + [list(SQUARE[0])]

    with pytest.raises(ValueError, match="open ring"):
        validate_polygon_points(closed, coordinate_range=NORMALIZED)


def test_duplicate_points_rejected():
    points = [[0.1, 0.2], [0.3, 0.2], [0.1, 0.2], [0.3, 0.5]]

    with pytest.raises(ValueError, match="duplicate"):
        validate_polygon_points(points, coordinate_range=NORMALIZED)


def test_zero_area_polygon_rejected():
    """모든 점이 한 직선 위에 있으면 면적이 0이다."""
    points = [[0.1, 0.1], [0.2, 0.2], [0.3, 0.3]]

    with pytest.raises(ValueError, match="zero area"):
        validate_polygon_points(points, coordinate_range=NORMALIZED)


def test_self_intersecting_polygon_rejected():
    """계약 fixture zones_invalid_polygon_422.json과 같은 bowtie 형태."""
    bowtie = [[0.1, 0.1], [0.3, 0.3], [0.1, 0.3], [0.3, 0.1]]

    with pytest.raises(ValueError, match="self-intersect"):
        validate_polygon_points(bowtie, coordinate_range=NORMALIZED)


@pytest.mark.parametrize("bad_point", [[1.1, 0.5], [0.5, -0.01]])
def test_out_of_normalized_range_rejected(bad_point):
    points = [[0.1, 0.2], [0.3, 0.2], bad_point]

    with pytest.raises(ValueError, match=r"out of range \[0.0, 1.0\]"):
        validate_polygon_points(points, coordinate_range=NORMALIZED)


def test_range_check_skipped_when_not_requested():
    """floor 좌표는 meter라 상한이 없다."""
    meters = [[0.0, 0.0], [6.0, 0.0], [6.0, 4.0], [0.0, 4.0]]

    assert validate_polygon_points(meters) == meters


@pytest.mark.parametrize("bad", [[[0.1, 0.2, 0.3], [0.3, 0.2], [0.3, 0.5]], "square", 42])
def test_malformed_input_rejected(bad):
    with pytest.raises(ValueError):
        validate_polygon_points(bad)


def test_label_appears_in_message():
    with pytest.raises(ValueError, match="zone 'danger_door' points"):
        validate_polygon_points([[0.0, 0.0]], label="zone 'danger_door' points")


def test_message_matches_frozen_422_contract_fixture():
    """`PUT /zones` 422 fixture의 입력과 메시지를 그대로 재현하는지 확인.

    fixture의 `msg`는 Pydantic이 붙이는 `Value error, ` 접두사를 포함한다.
    """
    import json

    with open(
        "tests/fixtures/phase4_contract/zones_invalid_polygon_422.json", "r", encoding="utf-8"
    ) as f:
        detail = json.load(f)["detail"][0]

    expected = detail["msg"].removeprefix("Value error, ")

    with pytest.raises(ValueError) as exc_info:
        validate_polygon_points(detail["input"], coordinate_range=NORMALIZED)

    assert str(exc_info.value) == expected
