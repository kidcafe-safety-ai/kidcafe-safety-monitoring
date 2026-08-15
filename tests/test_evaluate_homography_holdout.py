"""Homography holdout 평가 스크립트 테스트 (Phase 4 PoC).

공식 평가가 runtime config와 같은 fit 점을 쓰는지, 계약 미달을 스스로 보고하는지,
유한하지 않은 입력을 거부하는지 확인한다. 이 셋이 어긋나면 결과가 조용히 생성되고
공식 판정으로 오해된다.
"""

import csv
import json
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from evaluate_homography_holdout import (  # noqa: E402
    REQUIRED_HOLDOUT_POSITIONS,
    REQUIRED_OBSERVATIONS,
    HoldoutEvalError,
    choose_fit_sets,
    evaluate,
    fit_homography,
    load_floor_points,
    load_picked,
    summarize,
)

# 실측 좌표는 원단위 (y, x). role은 촬영 현장에서 정한 배정을 그대로 쓴다.
POINTS_CSV = "\n".join(
    [
        "point_id,role,y,x",
        "P01,fit,18,6",
        "P08,fit,67,44",
        "P09,fit,82,5",
        "P10,fit,17,36",
        "P02,holdout,9,19",
        "P03,holdout,36,13",
        "P04,holdout,31,40",
        "P05,holdout,48,32",
        "P06,holdout,56,8",
        "P07,holdout,73,21",
    ]
)

TRUE_HOMOGRAPHY = np.array(
    [[3.4, 0.35, 700.0], [0.22, -3.1, 980.0], [0.00021, -0.00095, 1.0]]
)


def project(x_m, y_m):
    vector = TRUE_HOMOGRAPHY @ np.array([x_m, y_m, 1.0])
    return vector[0] / vector[2], vector[1] / vector[2]


@pytest.fixture()
def points_path(tmp_path):
    path = tmp_path / "calibration_points.csv"
    path.write_text(POINTS_CSV + "\n", encoding="utf-8")
    return path


@pytest.fixture()
def floor_and_roles(points_path):
    return load_floor_points(points_path, 1.0)


def write_picked(tmp_path, floor, roles, name="picked.csv", jitter=0.0, seed=0):
    """참 homography로 픽셀을 만들어 클릭 결과 CSV를 흉내낸다."""
    rng = np.random.default_rng(seed)
    path = tmp_path / name
    with open(path, "w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(
            file, fieldnames=("point_id", "role", "pixel_x", "pixel_y"), lineterminator="\n"
        )
        writer.writeheader()
        for point_id, (x_m, y_m) in floor.items():
            px, py = project(x_m, y_m)
            writer.writerow(
                {
                    "point_id": point_id,
                    "role": roles[point_id],
                    "pixel_x": f"{px + rng.normal(0, jitter):.3f}",
                    "pixel_y": f"{py + rng.normal(0, jitter):.3f}",
                }
            )
    return path


# ============ role 파싱 ============


def test_load_floor_points_returns_roles(floor_and_roles):
    floor, roles = floor_and_roles

    assert len(floor) == 10
    assert sorted(p for p, r in roles.items() if r == "fit") == ["P01", "P08", "P09", "P10"]
    assert len(([p for p, r in roles.items() if r == "holdout"])) == 6


def test_unit_cm_scales_floor_coordinates(points_path):
    one_cm, _ = load_floor_points(points_path, 1.0)
    ten_cm, _ = load_floor_points(points_path, 10.0)

    assert ten_cm["P09"][1] == pytest.approx(one_cm["P09"][1] * 10)


@pytest.mark.parametrize("bad_role", ["", "FIT", "reference"])
def test_unknown_role_rejected(tmp_path, bad_role):
    path = tmp_path / "bad.csv"
    path.write_text(
        POINTS_CSV.replace("P02,holdout", f"P02,{bad_role}") + "\n", encoding="utf-8"
    )

    with pytest.raises(HoldoutEvalError, match="role"):
        load_floor_points(path, 1.0)


def test_too_few_fit_points_rejected(tmp_path):
    path = tmp_path / "few_fit.csv"
    path.write_text(POINTS_CSV.replace("P10,fit", "P10,holdout") + "\n", encoding="utf-8")

    with pytest.raises(HoldoutEvalError, match="role=fit"):
        load_floor_points(path, 1.0)


# ============ 공식 평가가 runtime과 같은 fit을 쓰는지 ============


def test_designated_mode_uses_only_role_fit(floor_and_roles):
    """runtime config는 role=fit 점만 담는다. 공식 평가도 같아야 한다."""
    floor, roles = floor_and_roles

    fit_sets = choose_fit_sets(floor, roles, "designated")

    assert set(fit_sets) == {"P02", "P03", "P04", "P05", "P06", "P07"}
    for fit in fit_sets.values():
        assert fit == ("P01", "P08", "P09", "P10")


def test_designated_mode_never_fits_on_a_holdout_point(floor_and_roles):
    floor, roles = floor_and_roles

    fit_sets = choose_fit_sets(floor, roles, "designated")

    holdout = {p for p, r in roles.items() if r == "holdout"}
    for target, fit in fit_sets.items():
        assert target in holdout
        assert not (set(fit) & holdout)


@pytest.mark.parametrize("mode", ["loo-all", "loo-quad"])
def test_diagnostic_modes_evaluate_every_point(floor_and_roles, mode):
    floor, roles = floor_and_roles

    fit_sets = choose_fit_sets(floor, roles, mode)

    assert set(fit_sets) == set(floor)
    for target, fit in fit_sets.items():
        assert target not in fit


def test_loo_quad_uses_exactly_four_fit_points(floor_and_roles):
    floor, roles = floor_and_roles

    fit_sets = choose_fit_sets(floor, roles, "loo-quad")

    assert all(len(fit) == 4 for fit in fit_sets.values())


# ============ 유한값 검증 ============


@pytest.mark.parametrize("bad", ["nan", "inf", "-inf"])
def test_non_finite_pixel_rejected(tmp_path, bad):
    path = tmp_path / "picked.csv"
    path.write_text(
        f"point_id,role,pixel_x,pixel_y\nP01,fit,{bad},500\n", encoding="utf-8"
    )

    with pytest.raises(HoldoutEvalError, match="유한"):
        load_picked(path, ["P01"])


def test_missing_point_rejected(tmp_path, floor_and_roles):
    floor, roles = floor_and_roles
    path = write_picked(tmp_path, floor, roles)
    rows = path.read_text(encoding="utf-8").splitlines()
    path.write_text("\n".join(rows[:-1]) + "\n", encoding="utf-8")

    with pytest.raises(HoldoutEvalError, match="없는 기준점"):
        load_picked(path, list(floor))


def test_duplicate_point_rejected(tmp_path, floor_and_roles):
    floor, roles = floor_and_roles
    path = write_picked(tmp_path, floor, roles)
    text = path.read_text(encoding="utf-8")
    path.write_text(text + text.splitlines()[1] + "\n", encoding="utf-8")

    with pytest.raises(HoldoutEvalError, match="중복"):
        load_picked(path, list(floor))


# ============ 행렬 추정 ============


def test_fit_homography_uses_exact_solution_for_four_points():
    src = np.float32([[0, 0], [100, 0], [100, 100], [0, 100]])
    dst = np.float32([[0, 0], [2, 0], [2, 2], [0, 2]])

    matrix = fit_homography(src, dst)

    assert matrix.shape == (3, 3)
    assert np.all(np.isfinite(matrix))


def test_fit_homography_least_squares_for_more_points(floor_and_roles):
    floor, _ = floor_and_roles
    ids = sorted(floor)
    src = np.float32([project(*floor[i]) for i in ids])
    dst = np.float32([floor[i] for i in ids])

    matrix = fit_homography(src, dst)

    assert np.all(np.isfinite(matrix))


# ============ 평가·계약 ============


def test_perfect_pixels_give_near_zero_error(tmp_path, floor_and_roles):
    """참 homography 그대로면 오차가 반올림 한계까지 내려가야 한다.

    클릭 결과 CSV는 픽셀을 소수점 3자리로 저장한다. 그 반올림이 fit 4점을 통해
    행렬로 들어가고 holdout 점에서 증폭되므로 0이 되지는 않는다. 실제 클릭 오차
    (1px 이상)보다 세 자릿수 작으면 변환 자체에는 결함이 없다고 본다.
    """
    floor, roles = floor_and_roles
    picked = load_picked(write_picked(tmp_path, floor, roles), list(floor))
    fit_sets = choose_fit_sets(floor, roles, "designated")

    observations = evaluate(floor, {"clip": picked}, fit_sets)

    assert max(o["error_m"] for o in observations) < 1e-3


def test_click_jitter_increases_error(tmp_path, floor_and_roles):
    floor, roles = floor_and_roles
    fit_sets = choose_fit_sets(floor, roles, "designated")
    clean = load_picked(write_picked(tmp_path, floor, roles, "a.csv"), list(floor))
    noisy = load_picked(
        write_picked(tmp_path, floor, roles, "b.csv", jitter=2.0, seed=7), list(floor)
    )

    clean_max = max(o["error_m"] for o in evaluate(floor, {"c": clean}, fit_sets))
    noisy_max = max(o["error_m"] for o in evaluate(floor, {"c": noisy}, fit_sets))

    assert noisy_max > clean_max


def test_designated_mode_reports_contract_shortfall(tmp_path, floor_and_roles):
    """fit 4·holdout 6으로는 계약(10위치·20관측)을 채울 수 없다."""
    floor, roles = floor_and_roles
    picked = load_picked(write_picked(tmp_path, floor, roles), list(floor))
    fit_sets = choose_fit_sets(floor, roles, "designated")

    observations = evaluate(floor, {"c1": picked, "c2": picked}, fit_sets)
    stats = summarize(observations)

    assert stats["position_count"] == 6
    assert stats["observation_count"] == 12
    assert stats["position_count"] < REQUIRED_HOLDOUT_POSITIONS
    assert stats["observation_count"] < REQUIRED_OBSERVATIONS


def test_interpolation_and_extrapolation_are_separated(tmp_path, floor_and_roles):
    floor, roles = floor_and_roles
    picked = load_picked(write_picked(tmp_path, floor, roles), list(floor))
    fit_sets = choose_fit_sets(floor, roles, "designated")

    observations = evaluate(floor, {"c": picked}, fit_sets)
    regions = {o["region"] for o in observations}

    assert regions <= {"interpolation", "extrapolation"}
    assert summarize(observations, "interpolation")["observation_count"] + summarize(
        observations, "extrapolation"
    )["observation_count"] == len(observations)


def test_every_observation_records_its_fit_points(tmp_path, floor_and_roles):
    """어떤 점으로 맞춘 결과인지 남아야 재현·감사가 가능하다."""
    floor, roles = floor_and_roles
    picked = load_picked(write_picked(tmp_path, floor, roles), list(floor))
    fit_sets = choose_fit_sets(floor, roles, "designated")

    for observation in evaluate(floor, {"c": picked}, fit_sets):
        assert observation["fit_points"] == ["P01", "P08", "P09", "P10"]
        assert np.isfinite(observation["error_m"])


def test_summary_uses_contract_percentile(tmp_path, floor_and_roles):
    """p95는 계약이 정한 numpy linear percentile이어야 한다."""
    floor, roles = floor_and_roles
    picked = load_picked(
        write_picked(tmp_path, floor, roles, jitter=1.5, seed=3), list(floor)
    )
    fit_sets = choose_fit_sets(floor, roles, "designated")

    observations = evaluate(floor, {"c": picked}, fit_sets)
    stats = summarize(observations)
    errors = [o["error_m"] for o in observations]

    assert stats["p95_m"] == pytest.approx(
        float(np.percentile(errors, 95, method="linear"))
    )
    assert stats["mean_m"] == pytest.approx(float(np.mean(errors)))


def test_official_mode_matches_runtime_config_transform(tmp_path, floor_and_roles):
    """공식 평가의 행렬이 runtime config로 만든 행렬과 같아야 한다.

    runtime은 fit 점만 담으므로, 둘이 다르면 배포되지 않는 시스템을 평가하는 것이다.
    """
    floor, roles = floor_and_roles
    picked = load_picked(write_picked(tmp_path, floor, roles), list(floor))
    fit = ("P01", "P08", "P09", "P10")

    runtime = cv2.getPerspectiveTransform(
        np.float32([picked[i] for i in fit]), np.float32([floor[i] for i in fit])
    )
    official = fit_homography(
        np.float32([picked[i] for i in fit]), np.float32([floor[i] for i in fit])
    )

    assert np.allclose(runtime / runtime[2, 2], official / official[2, 2])


def test_summary_of_empty_selection_is_empty():
    assert summarize([], "interpolation")["observation_count"] == 0


def test_result_is_reproducible(tmp_path, floor_and_roles):
    """같은 입력이면 같은 결과여야 한다. RANSAC이 섞이면 실행마다 달라진다."""
    floor, roles = floor_and_roles
    picked = load_picked(
        write_picked(tmp_path, floor, roles, jitter=1.0, seed=11), list(floor)
    )
    fit_sets = choose_fit_sets(floor, roles, "loo-all")

    first = evaluate(floor, {"c": picked}, fit_sets)
    second = evaluate(floor, {"c": picked}, fit_sets)

    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
