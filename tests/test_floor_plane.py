"""FloorPlaneTransformer와 calibration config 검증 테스트 (Phase 4 Homography PoC)."""

import copy
import json

import numpy as np
import pytest

from src.geofencing.floor_plane import (
    CalibrationError,
    CalibrationMismatchError,
    FloorPlaneTransformer,
    load_calibration,
    parse_calibration,
    position_errors_m,
    summarize_errors_m,
)

FIXTURE_PATH = "tests/fixtures/phase4_contract/calibration_runtime.json"


@pytest.fixture
def config_data():
    with open(FIXTURE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def transformer(config_data):
    return FloorPlaneTransformer(parse_calibration(config_data))


def write_config(tmp_path, data, name="cam01.json"):
    path = tmp_path / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


# ============ Config 검증 ============


def test_parse_contract_fixture(config_data):
    config = parse_calibration(config_data)

    assert config.schema_version == 1
    assert config.camera_id == "cam01"
    assert config.calibration_version == "cam01-20260807-v1"
    assert config.coordinate_unit == "meter"
    assert config.frame_width == 1920
    assert config.frame_height == 1080
    assert len(config.image_points_px) == len(config.floor_points) == 4


def test_default_enabled_is_false(config_data):
    """Homography는 기본 비활성 PoC다 (ADR-023)."""
    assert parse_calibration(config_data).enabled is False


@pytest.mark.parametrize("field", [
    "schema_version",
    "calibration_version",
    "enabled",
    "camera_id",
    "frame_size",
    "coordinate_unit",
    "origin_description",
    "image_points_px",
    "floor_points",
])
def test_missing_required_field(config_data, field):
    data = copy.deepcopy(config_data)
    del data[field]

    with pytest.raises(CalibrationError, match=f"'{field}'"):
        parse_calibration(data)


def test_unsupported_schema_version(config_data):
    data = copy.deepcopy(config_data)
    data["schema_version"] = 2

    with pytest.raises(CalibrationError, match="schema_version"):
        parse_calibration(data)


def test_coordinate_unit_must_be_meter(config_data):
    data = copy.deepcopy(config_data)
    data["coordinate_unit"] = "centimeter"

    with pytest.raises(CalibrationError, match="coordinate_unit"):
        parse_calibration(data)


@pytest.mark.parametrize("field", ["calibration_version", "camera_id", "origin_description"])
def test_blank_string_rejected(config_data, field):
    data = copy.deepcopy(config_data)
    data[field] = "   "

    with pytest.raises(CalibrationError, match=field):
        parse_calibration(data)


@pytest.mark.parametrize("width,height", [(0, 1080), (1920, -1), (1920.5, 1080)])
def test_invalid_frame_size(config_data, width, height):
    data = copy.deepcopy(config_data)
    data["frame_size"] = {"width": width, "height": height}

    with pytest.raises(CalibrationError, match="frame_size"):
        parse_calibration(data)


def test_point_count_mismatch(config_data):
    data = copy.deepcopy(config_data)
    data["floor_points"] = data["floor_points"][:3]

    with pytest.raises(CalibrationError, match="same length"):
        parse_calibration(data)


def test_fewer_than_four_fit_points(config_data):
    data = copy.deepcopy(config_data)
    data["image_points_px"] = data["image_points_px"][:3]
    data["floor_points"] = data["floor_points"][:3]

    with pytest.raises(CalibrationError, match="at least 4 fit points"):
        parse_calibration(data)


@pytest.mark.parametrize("bad_value", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_coordinate_rejected(config_data, bad_value):
    data = copy.deepcopy(config_data)
    data["floor_points"][0] = [bad_value, 0.0]

    with pytest.raises(CalibrationError, match="finite"):
        parse_calibration(data)


def test_duplicate_image_points_rejected(config_data):
    data = copy.deepcopy(config_data)
    data["image_points_px"][1] = list(data["image_points_px"][0])

    with pytest.raises(CalibrationError, match="duplicate"):
        parse_calibration(data)


def test_duplicate_floor_points_rejected(config_data):
    data = copy.deepcopy(config_data)
    data["floor_points"][2] = list(data["floor_points"][0])

    with pytest.raises(CalibrationError, match="duplicate"):
        parse_calibration(data)


def test_image_point_outside_frame_rejected(config_data):
    data = copy.deepcopy(config_data)
    data["image_points_px"][0] = [1920.1, 900.0]

    with pytest.raises(CalibrationError, match="outside the frame"):
        parse_calibration(data)


def test_collinear_image_points_rejected(config_data):
    data = copy.deepcopy(config_data)
    data["image_points_px"] = [[100.0, 100.0], [200.0, 200.0], [300.0, 300.0], [400.0, 400.0]]

    with pytest.raises(CalibrationError, match="single line"):
        parse_calibration(data)


def test_collinear_floor_points_rejected(config_data):
    data = copy.deepcopy(config_data)
    data["floor_points"] = [[0.0, 0.0], [1.0, 0.0], [2.0, 0.0], [3.0, 0.0]]

    with pytest.raises(CalibrationError, match="single line"):
        parse_calibration(data)


def test_malformed_point_pair_rejected(config_data):
    data = copy.deepcopy(config_data)
    data["image_points_px"][0] = [120.0, 900.0, 0.0]

    with pytest.raises(CalibrationError, match=r"\[x, y\] pair"):
        parse_calibration(data)


# ============ 파일 로드 ============


def test_load_calibration_from_file(tmp_path, config_data):
    config = load_calibration(write_config(tmp_path, config_data))

    assert config.camera_id == "cam01"


def test_load_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_calibration(str(tmp_path / "absent.json"))


def test_load_invalid_json_raises(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("{not json", encoding="utf-8")

    with pytest.raises(CalibrationError, match="Invalid JSON"):
        load_calibration(str(path))


def test_from_file_builds_transformer(tmp_path, config_data):
    transformer = FloorPlaneTransformer.from_file(write_config(tmp_path, config_data))

    assert transformer.camera_id == "cam01"
    assert transformer.calibration_version == "cam01-20260807-v1"
    assert transformer.enabled is False


# ============ 변환 ============


def test_fit_points_map_to_floor_points(transformer):
    """fit point는 자기 자신의 실측 floor 좌표로 되돌아와야 한다."""
    for image_point, expected in zip(
        transformer.config.image_points_px, transformer.config.floor_points
    ):
        result = transformer.transform(image_point)

        assert result == pytest.approx(expected, abs=1e-6)


def test_fit_residuals_are_near_zero(transformer):
    assert max(transformer.fit_residuals_m()) < 1e-6


def test_transform_many_preserves_order(transformer):
    points = transformer.config.image_points_px
    results = transformer.transform_many(points)

    assert len(results) == len(points)
    assert results[0] == pytest.approx(transformer.transform(points[0]))
    assert results[-1] == pytest.approx(transformer.transform(points[-1]))


def test_transform_interior_point_stays_within_floor(transformer):
    """fit 사각형 중앙 픽셀은 floor 사각형 내부로 변환된다."""
    image_points = np.asarray(transformer.config.image_points_px)
    center_px = image_points.mean(axis=0).tolist()

    floor_x, floor_y = transformer.transform(center_px)

    assert 0.0 < floor_x < 6.0
    assert 0.0 < floor_y < 4.0


def test_transform_is_monotonic_along_x(transformer):
    """같은 이미지 행에서 오른쪽 픽셀은 더 큰 floor X로 변환된다."""
    left = transformer.transform([300.0, 800.0])
    right = transformer.transform([1500.0, 800.0])

    assert right[0] > left[0]


def test_transform_recovers_synthetic_ground_truth():
    """알려진 homography로 만든 합성 대응점을 그대로 복원하는지 확인."""
    floor_points = [[0.0, 0.0], [6.0, 0.0], [6.0, 4.0], [0.0, 4.0]]
    truth = np.array(
        [
            [0.004, 0.0, -0.48],
            [0.0, -0.005, 4.5],
            [0.0, -0.0002, 1.0],
        ],
        dtype=np.float64,
    )
    inverse = np.linalg.inv(truth)

    image_points = []
    for fx, fy in floor_points:
        projected = inverse @ np.array([fx, fy, 1.0])
        image_points.append([projected[0] / projected[2], projected[1] / projected[2]])

    transformer = FloorPlaneTransformer(
        parse_calibration(
            {
                "schema_version": 1,
                "calibration_version": "synthetic-v1",
                "enabled": True,
                "camera_id": "synthetic",
                "frame_size": {"width": 1920, "height": 1080},
                "coordinate_unit": "meter",
                "origin_description": "synthetic origin",
                "image_points_px": image_points,
                "floor_points": floor_points,
            }
        )
    )

    probe_floor = [3.0, 2.0]
    projected = inverse @ np.array([probe_floor[0], probe_floor[1], 1.0])
    probe_px = [projected[0] / projected[2], projected[1] / projected[2]]

    assert transformer.transform(probe_px) == pytest.approx(probe_floor, abs=1e-6)


@pytest.mark.parametrize("bad_point", [[float("nan"), 0.0], [0.0, float("inf")]])
def test_transform_rejects_non_finite_point(transformer, bad_point):
    with pytest.raises(ValueError, match="finite"):
        transformer.transform(bad_point)


@pytest.mark.parametrize("bad_point", [[1.0], [1.0, 2.0, 3.0], "12"])
def test_transform_rejects_malformed_point(transformer, bad_point):
    with pytest.raises(ValueError, match=r"\[x, y\] pair"):
        transformer.transform(bad_point)


# ============ fail-fast ============


def test_verify_source_accepts_matching_input(transformer):
    transformer.verify_source("cam01", 1920, 1080)


def test_verify_source_rejects_camera_mismatch(transformer):
    with pytest.raises(CalibrationMismatchError, match="camera_id mismatch"):
        transformer.verify_source("cam02", 1920, 1080)


@pytest.mark.parametrize("width,height", [(1280, 1080), (1920, 720), (640, 480)])
def test_verify_source_rejects_resolution_mismatch(transformer, width, height):
    with pytest.raises(CalibrationMismatchError, match="frame size mismatch"):
        transformer.verify_source("cam01", width, height)


def test_mismatch_error_is_calibration_error(transformer):
    """호출자가 CalibrationError 하나로 잡아도 fallback 없이 실패한다."""
    with pytest.raises(CalibrationError):
        transformer.verify_source("cam02", 1920, 1080)


# ============ 오차 지표 ============


def test_position_errors_are_euclidean():
    errors = position_errors_m([[3.0, 4.0], [1.0, 1.0]], [[0.0, 0.0], [1.0, 1.0]])

    assert errors == pytest.approx([5.0, 0.0])


def test_position_errors_length_mismatch():
    with pytest.raises(ValueError, match="same length"):
        position_errors_m([[0.0, 0.0]], [[0.0, 0.0], [1.0, 1.0]])


def test_summarize_errors_matches_numpy_linear_percentile():
    errors = [0.01 * i for i in range(1, 21)]

    mean, p95 = summarize_errors_m(errors)

    assert mean == pytest.approx(float(np.mean(errors)))
    assert p95 == pytest.approx(float(np.percentile(errors, 95, method="linear")))


def test_summarize_errors_rejects_empty():
    with pytest.raises(ValueError, match="must not be empty"):
        summarize_errors_m([])


def test_holdout_fixture_has_contract_minimum():
    """holdout은 서로 다른 위치 10개·총 20회 이상 관측이어야 한다."""
    import csv

    with open(
        "tests/fixtures/phase4_contract/calibration_points.csv", "r", encoding="utf-8"
    ) as f:
        rows = list(csv.DictReader(f))

    holdout = [row for row in rows if row["point_role"] == "holdout"]
    fit = [row for row in rows if row["point_role"] == "fit"]

    assert len({row["point_id"] for row in holdout}) >= 10
    assert len(holdout) >= 20
    assert len(fit) >= 4
    assert not {row["point_id"] for row in holdout} & {row["point_id"] for row in fit}
