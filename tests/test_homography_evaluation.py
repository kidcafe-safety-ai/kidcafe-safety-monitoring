"""Homography 채택 판정 테스트 (`homography_acceptance_v1`)."""

import copy
import json

import numpy as np
import pytest

from src.geofencing.homography_evaluation import (
    AcceptanceError,
    EventErrorSummary,
    ZoneDecisionSummary,
    evaluate_acceptance,
    load_acceptance,
    parse_acceptance,
    position_errors_m,
    reduction_ratio,
    require_frozen,
    summarize_errors_m,
    summarize_zone_decisions,
)

FIXTURE_PATH = "tests/fixtures/phase4_contract/homography_acceptance.json"


@pytest.fixture
def acceptance_data():
    with open(FIXTURE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def frozen(acceptance_data):
    """촬영 후 허용값을 동결한 상태를 흉내낸다."""
    data = copy.deepcopy(acceptance_data)
    data["max_mean_error_m"] = 0.15
    data["max_p95_error_m"] = 0.30
    data["frozen_at"] = "2026-08-07T14:00:00Z"
    data["review_status"] = "reviewed"
    return data


def passing_measurements():
    return {
        "mean_error_m": 0.08,
        "p95_error_m": 0.18,
        "baseline_zone": ZoneDecisionSummary(total=100, errors=20),
        "homography_zone": ZoneDecisionSummary(total=100, errors=10),
        "baseline_event_errors": EventErrorSummary(missed=6, false_events=3, extra=1),
        "homography_event_errors": EventErrorSummary(missed=2, false_events=1, extra=0),
        "baseline_fast_reversals": 5,
        "homography_fast_reversals": 3,
        "added_latency_ms_per_frame": 0.4,
        "fps_drop_ratio": 0.02,
        "calibration_minutes": 11.0,
    }


# ============ 설정 검증 ============


def test_contract_fixture_parses(acceptance_data):
    data = parse_acceptance(acceptance_data)

    assert data["protocol_version"] == "homography_acceptance_v1"
    assert data["min_zone_error_reduction_ratio"] == 0.3
    assert data["max_fps_drop_ratio"] == 0.05


def test_contract_fixture_starts_unfrozen(acceptance_data):
    """촬영 전에는 절대 오차 허용값이 비어 있어야 한다."""
    assert acceptance_data["max_mean_error_m"] is None
    assert acceptance_data["max_p95_error_m"] is None
    assert acceptance_data["frozen_at"] is None
    assert acceptance_data["review_status"] == "pending"


def test_wrong_protocol_version_rejected(acceptance_data):
    data = copy.deepcopy(acceptance_data)
    data["protocol_version"] = "homography_acceptance_v2"

    with pytest.raises(AcceptanceError, match="protocol_version"):
        parse_acceptance(data)


@pytest.mark.parametrize("field", ["protocol_version", "camera_id", "frozen_at", "review_status"])
def test_missing_field_rejected(acceptance_data, field):
    data = copy.deepcopy(acceptance_data)
    del data[field]

    with pytest.raises(AcceptanceError, match=field):
        parse_acceptance(data)


@pytest.mark.parametrize("value", [0, -0.1, "0.1", True])
def test_invalid_error_limit_rejected(acceptance_data, value):
    data = copy.deepcopy(acceptance_data)
    data["max_mean_error_m"] = value

    with pytest.raises(AcceptanceError, match="max_mean_error_m"):
        parse_acceptance(data)


def test_load_acceptance_from_file():
    assert load_acceptance(FIXTURE_PATH)["camera_id"] == "cam01"


def test_load_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_acceptance(str(tmp_path / "absent.json"))


# ============ 동결 게이트 ============


def test_require_frozen_rejects_unfrozen_limits(acceptance_data):
    with pytest.raises(AcceptanceError, match="not frozen yet"):
        require_frozen(acceptance_data)


def test_require_frozen_rejects_missing_frozen_at(frozen):
    data = copy.deepcopy(frozen)
    data["frozen_at"] = None

    with pytest.raises(AcceptanceError, match="frozen_at"):
        require_frozen(data)


def test_require_frozen_accepts_frozen(frozen):
    require_frozen(frozen)


def test_evaluate_refuses_before_freeze(acceptance_data):
    """허용값 동결 전에는 holdout 판정을 아예 거부한다."""
    with pytest.raises(AcceptanceError, match="not frozen yet"):
        evaluate_acceptance(acceptance_data, **passing_measurements())


@pytest.mark.parametrize("status", ["pending", "needs_review", "frozen", "", None])
def test_require_frozen_rejects_non_reviewed_status(frozen, status):
    """동결 상태는 계약대로 `reviewed`여야 한다 (docs/interfaces.md)."""
    data = copy.deepcopy(frozen)
    data["review_status"] = status

    with pytest.raises(AcceptanceError, match="review_status"):
        require_frozen(data)


@pytest.mark.parametrize(
    "frozen_at",
    ["아무말이나", "2026-08-07", "2026-08-07T14:00:00", "14:00:00", "2026-13-07T00:00:00Z"],
)
def test_require_frozen_rejects_bad_frozen_at_format(frozen, frozen_at):
    """`frozen_at`은 timezone을 포함한 RFC 3339여야 한다."""
    data = copy.deepcopy(frozen)
    data["frozen_at"] = frozen_at

    with pytest.raises(AcceptanceError, match="frozen_at"):
        require_frozen(data)


@pytest.mark.parametrize(
    "frozen_at", ["2026-08-07T14:00:00Z", "2026-08-07T23:00:00+09:00"]
)
def test_require_frozen_accepts_rfc3339_with_timezone(frozen, frozen_at):
    data = copy.deepcopy(frozen)
    data["frozen_at"] = frozen_at

    require_frozen(data)


# ============ 측정값 유효 범위 ============


@pytest.mark.parametrize(
    "field",
    [
        "mean_error_m",
        "p95_error_m",
        "added_latency_ms_per_frame",
        "fps_drop_ratio",
        "calibration_minutes",
    ],
)
def test_negative_measurement_is_rejected(frozen, field):
    """음수 오차·시간은 물리적으로 불가능하다. 통과시키면 모든 임계값을 만족한다."""
    measurements = passing_measurements()
    measurements[field] = -1.0

    with pytest.raises(AcceptanceError, match=field):
        evaluate_acceptance(frozen, **measurements)


@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
def test_non_finite_measurement_is_rejected(frozen, bad):
    measurements = passing_measurements()
    measurements["mean_error_m"] = bad

    with pytest.raises(AcceptanceError, match="mean_error_m"):
        evaluate_acceptance(frozen, **measurements)


@pytest.mark.parametrize(
    "field", ["baseline_fast_reversals", "homography_fast_reversals"]
)
def test_negative_reversal_count_is_rejected(frozen, field):
    measurements = passing_measurements()
    measurements[field] = -1

    with pytest.raises(AcceptanceError, match=field):
        evaluate_acceptance(frozen, **measurements)


def test_p95_smaller_than_mean_is_rejected(frozen):
    """p95는 정의상 평균보다 작을 수 없다."""
    measurements = passing_measurements()
    measurements.update(mean_error_m=0.10, p95_error_m=0.05)

    with pytest.raises(AcceptanceError, match="p95_error_m"):
        evaluate_acceptance(frozen, **measurements)


def test_mismatched_zone_observation_counts_are_rejected(frozen):
    """두 방식은 동일 입력으로 비교해야 하므로 관측 수가 같아야 한다."""
    measurements = passing_measurements()
    measurements["homography_zone"] = ZoneDecisionSummary(total=7, errors=0)

    with pytest.raises(AcceptanceError, match="zone observation counts"):
        evaluate_acceptance(frozen, **measurements)


def test_fail_open_regression_is_closed(frozen):
    """리뷰에서 지적된 fail-open 조합이 더 이상 통과하지 않는다.

    이전에는 `review_status="pending"`, 잘못된 `frozen_at`, 음수 오차·시간,
    서로 다른 Zone 관측 수를 함께 넣어도 `passed == True`가 나왔다.
    """
    data = copy.deepcopy(frozen)
    data["review_status"] = "pending"
    data["frozen_at"] = "아무말이나"
    measurements = passing_measurements()
    measurements.update(
        mean_error_m=-5.0,
        p95_error_m=-1.0,
        homography_zone=ZoneDecisionSummary(total=7, errors=0),
        added_latency_ms_per_frame=-1.0,
        fps_drop_ratio=-0.5,
        calibration_minutes=-99.0,
    )

    with pytest.raises(AcceptanceError):
        evaluate_acceptance(data, **measurements)


# ============ 관측 요약 범위 ============


def test_zone_summary_rejects_errors_above_total():
    with pytest.raises(ValueError, match=r"\[0, 10\]"):
        ZoneDecisionSummary(total=10, errors=11)


def test_zone_summary_rejects_negative_errors():
    with pytest.raises(ValueError, match=r"\[0, 10\]"):
        ZoneDecisionSummary(total=10, errors=-1)


@pytest.mark.parametrize("total", [0, -1])
def test_zone_summary_rejects_non_positive_total(total):
    with pytest.raises(ValueError, match="no reviewed observations"):
        ZoneDecisionSummary(total=total, errors=0)


@pytest.mark.parametrize("field", ["missed", "false_events", "extra"])
def test_event_error_summary_rejects_negative(field):
    kwargs = {"missed": 1, "false_events": 1, "extra": 1}
    kwargs[field] = -1

    with pytest.raises(ValueError, match=field):
        EventErrorSummary(**kwargs)


# ============ 지표 계산 ============


def test_summarize_zone_decisions_counts_mismatches():
    summary = summarize_zone_decisions(
        [True, True, False, False], [True, False, False, True]
    )

    assert summary.total == 4
    assert summary.errors == 2
    assert summary.accuracy == pytest.approx(0.5)
    assert summary.accuracy_percentage == pytest.approx(50.0)


def test_summarize_zone_decisions_length_mismatch():
    with pytest.raises(ValueError, match="same length"):
        summarize_zone_decisions([True], [True, False])


def test_summarize_zone_decisions_rejects_empty():
    with pytest.raises(ValueError, match="must not be empty"):
        summarize_zone_decisions([], [])


def test_accuracy_requires_observations():
    with pytest.raises(ValueError, match="no reviewed observations"):
        ZoneDecisionSummary(total=0, errors=0).accuracy


def test_event_error_summary_totals():
    assert EventErrorSummary(missed=2, false_events=3, extra=1).total == 6


def test_reduction_ratio():
    assert reduction_ratio(10, 4) == pytest.approx(0.6)
    assert reduction_ratio(10, 10) == pytest.approx(0.0)


def test_reduction_ratio_is_none_when_baseline_clean():
    assert reduction_ratio(0, 0) is None


def test_reduction_ratio_rejects_negative():
    with pytest.raises(ValueError, match="must not be negative"):
        reduction_ratio(-1, 0)


# ============ 채택 판정 ============


def test_all_criteria_pass(frozen):
    result = evaluate_acceptance(frozen, **passing_measurements())

    assert result.passed is True
    assert result.failed_criteria == []
    assert len(result.criteria) == 9


@pytest.mark.parametrize(
    "override,failed_name",
    [
        # p95 >= mean을 유지하면서 평균만 허용값을 넘긴다.
        ({"mean_error_m": 0.20, "p95_error_m": 0.25}, "mean_position_error"),
        ({"p95_error_m": 0.40}, "p95_position_error"),
        ({"added_latency_ms_per_frame": 1.5}, "added_latency_per_frame"),
        ({"fps_drop_ratio": 0.09}, "fps_drop_ratio"),
        ({"calibration_minutes": 22.0}, "calibration_time"),
        ({"homography_fast_reversals": 9}, "no_new_fast_reversals"),
    ],
)
def test_single_threshold_failure_blocks_adoption(frozen, override, failed_name):
    measurements = passing_measurements()
    measurements.update(override)

    result = evaluate_acceptance(frozen, **measurements)

    assert result.passed is False
    assert [c.name for c in result.failed_criteria] == [failed_name]


def test_zone_accuracy_must_improve(frozen):
    measurements = passing_measurements()
    measurements["homography_zone"] = ZoneDecisionSummary(total=100, errors=20)

    result = evaluate_acceptance(frozen, **measurements)

    assert result.passed is False
    assert "zone_accuracy_improved" in [c.name for c in result.failed_criteria]


def test_zone_criterion_accepts_accuracy_gain_without_ratio(frozen):
    """오류 감소가 30% 미만이어도 정확도 5%p 이상 개선이면 통과한다."""
    measurements = passing_measurements()
    measurements["baseline_zone"] = ZoneDecisionSummary(total=100, errors=20)
    measurements["homography_zone"] = ZoneDecisionSummary(total=100, errors=15)

    result = evaluate_acceptance(frozen, **measurements)

    zone = next(c for c in result.criteria if c.name == "zone_error_reduction_or_accuracy_gain")
    assert zone.passed is True


def test_zone_criterion_fails_when_neither_condition_met(frozen):
    measurements = passing_measurements()
    measurements["baseline_zone"] = ZoneDecisionSummary(total=100, errors=20)
    measurements["homography_zone"] = ZoneDecisionSummary(total=100, errors=19)

    result = evaluate_acceptance(frozen, **measurements)

    assert result.passed is False
    assert "zone_error_reduction_or_accuracy_gain" in [
        c.name for c in result.failed_criteria
    ]


def test_not_adopted_when_baseline_has_no_zone_errors(frozen):
    """기존 방식에 오류가 없으면 채택하지 않는다."""
    measurements = passing_measurements()
    measurements["baseline_zone"] = ZoneDecisionSummary(total=100, errors=0)
    measurements["homography_zone"] = ZoneDecisionSummary(total=100, errors=0)

    result = evaluate_acceptance(frozen, **measurements)

    zone = next(c for c in result.criteria if c.name == "zone_error_reduction_or_accuracy_gain")
    assert zone.passed is False
    assert "0 zone errors" in zone.detail


def test_not_adopted_when_baseline_has_no_event_errors(frozen):
    measurements = passing_measurements()
    measurements["baseline_event_errors"] = EventErrorSummary(0, 0, 0)
    measurements["homography_event_errors"] = EventErrorSummary(0, 0, 0)

    result = evaluate_acceptance(frozen, **measurements)

    event = next(c for c in result.criteria if c.name == "event_error_reduction")
    assert event.passed is False


def test_event_error_reduction_below_limit_fails(frozen):
    measurements = passing_measurements()
    measurements["baseline_event_errors"] = EventErrorSummary(missed=10, false_events=0, extra=0)
    measurements["homography_event_errors"] = EventErrorSummary(missed=8, false_events=0, extra=0)

    result = evaluate_acceptance(frozen, **measurements)

    assert result.passed is False
    assert "event_error_reduction" in [c.name for c in result.failed_criteria]


def test_boundary_values_are_inclusive(frozen):
    """한계값과 정확히 같으면 통과다."""
    measurements = passing_measurements()
    measurements.update(
        mean_error_m=0.15,
        p95_error_m=0.30,
        added_latency_ms_per_frame=1.0,
        fps_drop_ratio=0.05,
        calibration_minutes=15.0,
        baseline_zone=ZoneDecisionSummary(total=100, errors=10),
        homography_zone=ZoneDecisionSummary(total=100, errors=7),
        baseline_event_errors=EventErrorSummary(missed=10, false_events=0, extra=0),
        homography_event_errors=EventErrorSummary(missed=7, false_events=0, extra=0),
        baseline_fast_reversals=3,
        homography_fast_reversals=3,
    )

    result = evaluate_acceptance(frozen, **measurements)

    assert result.passed is True


def test_criteria_details_are_reportable(frozen):
    result = evaluate_acceptance(frozen, **passing_measurements())

    assert all(c.detail for c in result.criteria)
    assert len({c.name for c in result.criteria}) == len(result.criteria)


# ============ 위치 오차 지표 ============


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
