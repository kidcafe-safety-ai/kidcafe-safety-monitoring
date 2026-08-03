"""Homography PoC 비교 지표와 채택 판정 (`homography_acceptance_v1`).

촬영 전에 지표 정의와 판정 로직을 고정해 두고, 촬영 후에는 측정값만 넣는다.
허용값을 동결하지 않은 상태에서는 판정 자체를 거부해 holdout 결과를 보고
기준을 완화하는 경로를 막는다 (ADR-023).

기준·정의: docs/homography_calibration.md 6절, docs/interfaces.md `Homography 평가`
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

import numpy as np

PROTOCOL_VERSION = "homography_acceptance_v1"
# 동결 상태값. docs/interfaces.md가 `review_status=reviewed`로 정의한다.
FROZEN_REVIEW_STATUS = "reviewed"

# `homography_acceptance_v1`이 이미 동결한 상대 기준값이다. 촬영 당일 정하는
# 절대 오차 허용값과 달리 이 값들은 바뀌면 안 된다. 최소 기준을 음수로, 최대
# 기준을 큰 값으로 바꾸면 성능이 악화된 측정값도 전부 통과하기 때문이다.
FROZEN_THRESHOLDS = {
    "min_zone_error_reduction_ratio": 0.30,
    "min_zone_accuracy_gain_percentage_point": 5.0,
    "min_event_error_reduction_ratio": 0.30,
    "max_added_latency_ms_per_frame": 1.0,
    "max_fps_drop_ratio": 0.05,
    "max_calibration_minutes": 15,
}

REQUIRED_ACCEPTANCE_FIELDS = (
    "protocol_version",
    "camera_id",
    "calibration_version",
    "max_mean_error_m",
    "max_p95_error_m",
    "min_zone_error_reduction_ratio",
    "min_zone_accuracy_gain_percentage_point",
    "min_event_error_reduction_ratio",
    "max_added_latency_ms_per_frame",
    "max_fps_drop_ratio",
    "max_calibration_minutes",
    "frozen_at",
    "review_status",
)


class AcceptanceError(ValueError):
    """Acceptance 설정이 계약을 만족하지 않거나 아직 동결되지 않음."""


@dataclass(frozen=True)
class ZoneDecisionSummary:
    """Zone inside/outside 판정 요약.

    분모는 판정 가능한 reviewed holdout 관측 전체다.
    """

    total: int
    errors: int

    def __post_init__(self) -> None:
        if not isinstance(self.total, int) or isinstance(self.total, bool):
            raise ValueError("zone decision total must be an integer")
        if not isinstance(self.errors, int) or isinstance(self.errors, bool):
            raise ValueError("zone decision errors must be an integer")
        if self.total <= 0:
            raise ValueError("zone decision summary has no reviewed observations")
        if not (0 <= self.errors <= self.total):
            raise ValueError(
                f"zone decision errors must be in [0, {self.total}]: got {self.errors}"
            )

    @property
    def accuracy(self) -> float:
        """0.0-1.0."""
        return (self.total - self.errors) / self.total

    @property
    def accuracy_percentage(self) -> float:
        return self.accuracy * 100.0


@dataclass(frozen=True)
class EventErrorSummary:
    """reviewed interval 대비 ENTER·EXIT Event 오류."""

    missed: int
    false_events: int
    extra: int

    def __post_init__(self) -> None:
        for name in ("missed", "false_events", "extra"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool):
                raise ValueError(f"event error '{name}' must be an integer")
            if value < 0:
                raise ValueError(f"event error '{name}' must not be negative: got {value}")

    @property
    def total(self) -> int:
        return self.missed + self.false_events + self.extra


@dataclass(frozen=True)
class Criterion:
    name: str
    passed: bool
    detail: str


@dataclass
class AcceptanceResult:
    criteria: List[Criterion] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        """모든 기준을 만족할 때만 채택한다."""
        return bool(self.criteria) and all(c.passed for c in self.criteria)

    @property
    def failed_criteria(self) -> List[Criterion]:
        return [c for c in self.criteria if not c.passed]


def summarize_zone_decisions(
    predicted: Sequence[bool],
    expected: Sequence[bool],
) -> ZoneDecisionSummary:
    """예측·정답 inside/outside 판정을 비교해 요약."""
    if len(predicted) != len(expected):
        raise ValueError(
            f"predicted ({len(predicted)}) and expected ({len(expected)}) "
            f"must have the same length"
        )
    if not predicted:
        raise ValueError("zone decisions must not be empty")

    errors = sum(1 for p, e in zip(predicted, expected) if bool(p) != bool(e))
    return ZoneDecisionSummary(total=len(predicted), errors=errors)


def reduction_ratio(baseline: int, candidate: int) -> Optional[float]:
    """기존 대비 감소 비율. 기존 오류가 0이면 판정 불가라 `None`을 반환한다."""
    if baseline < 0 or candidate < 0:
        raise ValueError("counts must not be negative")
    if baseline == 0:
        return None
    return (baseline - candidate) / baseline


def parse_acceptance(data: dict) -> dict:
    """Acceptance 설정을 검증한다.

    Raises:
        AcceptanceError: 필수 필드 누락, protocol version 불일치, 또는 타입 오류
    """
    if not isinstance(data, dict):
        raise AcceptanceError("acceptance config must be a JSON object")

    for field_name in REQUIRED_ACCEPTANCE_FIELDS:
        if field_name not in data:
            raise AcceptanceError(f"missing required field: '{field_name}'")

    if data["protocol_version"] != PROTOCOL_VERSION:
        raise AcceptanceError(
            f"protocol_version must be '{PROTOCOL_VERSION}': got '{data['protocol_version']}'"
        )

    for field_name in ("camera_id", "calibration_version", "review_status"):
        value = data[field_name]
        if not isinstance(value, str) or not value.strip():
            raise AcceptanceError(f"'{field_name}' must be a non-empty string")

    for field_name, expected in FROZEN_THRESHOLDS.items():
        value = data[field_name]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise AcceptanceError(f"'{field_name}' must be a number")
        if not math.isfinite(value) or not math.isclose(value, expected, rel_tol=1e-9):
            raise AcceptanceError(
                f"'{field_name}' is frozen by {PROTOCOL_VERSION} and must stay "
                f"{expected}: got {value!r}"
            )

    for field_name in ("max_mean_error_m", "max_p95_error_m"):
        value = data[field_name]
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise AcceptanceError(f"'{field_name}' must be a positive number or null")
        if not math.isfinite(value) or value <= 0:
            raise AcceptanceError(
                f"'{field_name}' must be a finite positive number or null: got {value!r}"
            )

    return data


def load_acceptance(json_path: str) -> dict:
    """Acceptance 설정 파일을 로드해 검증.

    Raises:
        FileNotFoundError: 파일이 없음
        AcceptanceError: JSON 형식 오류 또는 계약 위반
    """
    path = Path(json_path)
    if not path.exists():
        raise FileNotFoundError(f"Acceptance file not found: {json_path}")

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise AcceptanceError(f"Invalid JSON in {json_path}: {e}")

    return parse_acceptance(data)


def require_frozen(acceptance: dict) -> None:
    """holdout 결과를 보기 전에 허용값이 동결됐는지 확인.

    절대 오차 허용값은 8월 7일 실측 이후·holdout 확인 이전에 동결한다. 동결
    전에 판정을 시도하면 기준을 결과에 맞춰 고르는 것과 같으므로 막는다.

    Raises:
        AcceptanceError: 허용값·`frozen_at`·`review_status`가 동결 상태가 아님
    """
    for field_name in ("max_mean_error_m", "max_p95_error_m"):
        if acceptance.get(field_name) is None:
            raise AcceptanceError(
                f"'{field_name}' is not frozen yet; freeze absolute error limits from the "
                f"2026-08-07 site measurements before looking at holdout results"
            )

    frozen_at = acceptance.get("frozen_at")
    if not isinstance(frozen_at, str) or not frozen_at.strip():
        raise AcceptanceError("'frozen_at' must be set before evaluating holdout results")
    _require_rfc3339_with_timezone(frozen_at)

    review_status = acceptance.get("review_status")
    if review_status != FROZEN_REVIEW_STATUS:
        raise AcceptanceError(
            f"'review_status' must be '{FROZEN_REVIEW_STATUS}' before evaluating holdout "
            f"results: got {review_status!r}"
        )


def _require_rfc3339_with_timezone(value: str) -> None:
    """`frozen_at`은 timezone을 포함한 RFC 3339여야 한다.

    동결 시각이 모호하면 "holdout 확인 전에 동결했다"를 사후에 증명할 수 없다.

    `datetime.fromisoformat`은 Python 3.10까지 `Z` suffix를 파싱하지 못한다.
    CI가 3.10이므로 UTC offset으로 바꿔서 넘긴다.
    """
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = f"{text[:-1]}+00:00"

    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise AcceptanceError(
            f"'frozen_at' must be an RFC 3339 datetime: got {value!r}"
        )
    if parsed.tzinfo is None:
        raise AcceptanceError(f"'frozen_at' must include a timezone: got {value!r}")


def _require_finite(name: str, value: float) -> float:
    """측정값이 finite한 수인지 확인한다.

    NaN·Infinity는 임계값 비교를 무의미하게 만든다. `NaN <= limit`은 항상
    False라 조용히 미채택이 되고, `-inf`는 항상 통과한다.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AcceptanceError(f"'{name}' must be a number: got {value!r}")
    if not math.isfinite(value):
        raise AcceptanceError(f"'{name}' must be finite: got {value!r}")
    return float(value)


def _require_finite_non_negative(name: str, value: float) -> float:
    """거리·시간처럼 절대량인 측정값을 확인한다.

    음수는 물리적으로 불가능하므로 측정·기록 오류다. 조용히 통과시키면 모든
    임계값 비교를 자동으로 만족해 채택 판정이 무의미해진다.
    """
    number = _require_finite(name, value)
    if number < 0:
        raise AcceptanceError(f"'{name}' must not be negative: got {number}")
    return number


def _require_non_negative_count(name: str, value: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise AcceptanceError(f"'{name}' must be an integer: got {value!r}")
    if value < 0:
        raise AcceptanceError(f"'{name}' must not be negative: got {value}")
    return value


def evaluate_acceptance(
    acceptance: dict,
    *,
    mean_error_m: float,
    p95_error_m: float,
    baseline_zone: ZoneDecisionSummary,
    homography_zone: ZoneDecisionSummary,
    baseline_event_errors: EventErrorSummary,
    homography_event_errors: EventErrorSummary,
    baseline_fast_reversals: int,
    homography_fast_reversals: int,
    added_latency_ms_per_frame: float,
    fps_drop_ratio: float,
    calibration_minutes: float,
) -> AcceptanceResult:
    """채택 기준을 하나씩 판정해 결과를 모은다.

    모든 기준을 만족할 때만 `passed`가 True다. 하나라도 실패하면 기존 image
    polygon을 유지하고 미채택 사유로 기록한다.

    Raises:
        AcceptanceError: 허용값이 동결되지 않았거나 측정값이 유효 범위를 벗어남
    """
    parse_acceptance(acceptance)
    require_frozen(acceptance)

    # 거리·시간은 절대량이라 음수가 물리적으로 불가능하다.
    mean_error_m = _require_finite_non_negative("mean_error_m", mean_error_m)
    p95_error_m = _require_finite_non_negative("p95_error_m", p95_error_m)
    calibration_minutes = _require_finite_non_negative(
        "calibration_minutes", calibration_minutes
    )

    # 반면 아래 둘은 기준선 대비 차이라 후보 경로가 더 빠르면 음수가 나올 수
    # 있다. 측정값을 그대로 보존하고 finite만 확인한다. 음수는 "하락 없음"이라
    # 임계값 비교를 자연히 통과한다.
    added_latency_ms_per_frame = _require_finite(
        "added_latency_ms_per_frame", added_latency_ms_per_frame
    )
    fps_drop_ratio = _require_finite("fps_drop_ratio", fps_drop_ratio)

    baseline_fast_reversals = _require_non_negative_count(
        "baseline_fast_reversals", baseline_fast_reversals
    )
    homography_fast_reversals = _require_non_negative_count(
        "homography_fast_reversals", homography_fast_reversals
    )

    # p95와 평균의 대소는 강제하지 않는다. 왜곡된 분포에서는 평균이 p95보다 클
    # 수 있다. 예: 오차 21개가 0m 20개와 100m 1개면 평균 4.76m, p95 0m이다.

    # 두 방식은 동일 frame·Track·foot point 입력으로 비교한다. 관측 수가 다르면
    # 같은 조건에서 잰 것이 아니므로 정확도·오류 수 비교가 성립하지 않는다.
    if baseline_zone.total != homography_zone.total:
        raise AcceptanceError(
            f"zone observation counts must match: baseline {baseline_zone.total} "
            f"vs homography {homography_zone.total}"
        )

    criteria: List[Criterion] = []

    criteria.append(
        _threshold(
            "mean_position_error",
            mean_error_m,
            acceptance["max_mean_error_m"],
            unit="m",
        )
    )
    criteria.append(
        _threshold(
            "p95_position_error",
            p95_error_m,
            acceptance["max_p95_error_m"],
            unit="m",
        )
    )

    baseline_accuracy = baseline_zone.accuracy_percentage
    homography_accuracy = homography_zone.accuracy_percentage
    criteria.append(
        Criterion(
            name="zone_accuracy_improved",
            passed=homography_accuracy > baseline_accuracy,
            detail=(
                f"{baseline_accuracy:.2f}%p baseline -> {homography_accuracy:.2f}%p homography"
            ),
        )
    )

    criteria.append(
        _zone_error_criterion(
            acceptance,
            baseline_zone=baseline_zone,
            homography_zone=homography_zone,
            accuracy_gain=homography_accuracy - baseline_accuracy,
        )
    )

    criteria.append(
        _event_error_criterion(
            acceptance,
            baseline=baseline_event_errors,
            candidate=homography_event_errors,
        )
    )

    criteria.append(
        Criterion(
            name="no_new_fast_reversals",
            passed=homography_fast_reversals <= baseline_fast_reversals,
            detail=f"{baseline_fast_reversals} baseline -> {homography_fast_reversals} homography",
        )
    )

    criteria.append(
        _threshold(
            "added_latency_per_frame",
            added_latency_ms_per_frame,
            acceptance["max_added_latency_ms_per_frame"],
            unit="ms",
        )
    )
    criteria.append(
        _threshold("fps_drop_ratio", fps_drop_ratio, acceptance["max_fps_drop_ratio"], unit="")
    )
    criteria.append(
        _threshold(
            "calibration_time",
            calibration_minutes,
            acceptance["max_calibration_minutes"],
            unit="min",
        )
    )

    return AcceptanceResult(criteria=criteria)


def _threshold(name: str, value: float, limit: float, *, unit: str) -> Criterion:
    suffix = f" {unit}" if unit else ""
    return Criterion(
        name=name,
        passed=value <= limit,
        detail=f"{value:.4f}{suffix} (limit {limit}{suffix})",
    )


def _zone_error_criterion(
    acceptance: dict,
    *,
    baseline_zone: ZoneDecisionSummary,
    homography_zone: ZoneDecisionSummary,
    accuracy_gain: float,
) -> Criterion:
    """Zone 오류 30% 이상 감소 **또는** 정확도 5%p 이상 개선."""
    min_reduction = acceptance["min_zone_error_reduction_ratio"]
    min_gain = acceptance["min_zone_accuracy_gain_percentage_point"]

    ratio = reduction_ratio(baseline_zone.errors, homography_zone.errors)
    if ratio is None:
        return Criterion(
            name="zone_error_reduction_or_accuracy_gain",
            passed=False,
            detail=(
                "baseline had 0 zone errors; homography is not adopted when the existing "
                "path produces no errors"
            ),
        )

    passed = ratio >= min_reduction or accuracy_gain >= min_gain
    return Criterion(
        name="zone_error_reduction_or_accuracy_gain",
        passed=passed,
        detail=(
            f"errors {baseline_zone.errors} -> {homography_zone.errors} "
            f"(reduction {ratio:.4f}, limit {min_reduction}); "
            f"accuracy gain {accuracy_gain:.2f}%p (limit {min_gain}%p)"
        ),
    )


def _event_error_criterion(
    acceptance: dict,
    *,
    baseline: EventErrorSummary,
    candidate: EventErrorSummary,
) -> Criterion:
    min_reduction = acceptance["min_event_error_reduction_ratio"]
    ratio = reduction_ratio(baseline.total, candidate.total)

    if ratio is None:
        return Criterion(
            name="event_error_reduction",
            passed=False,
            detail=(
                "baseline had 0 ENTER/EXIT event errors; homography is not adopted when the "
                "existing path produces no errors"
            ),
        )

    return Criterion(
        name="event_error_reduction",
        passed=ratio >= min_reduction,
        detail=(
            f"errors {baseline.total} -> {candidate.total} "
            f"(reduction {ratio:.4f}, limit {min_reduction})"
        ),
    )


def position_errors_m(
    predicted: Sequence[Sequence[float]],
    expected: Sequence[Sequence[float]],
) -> List[float]:
    """예측·실측 floor point 쌍의 meter 단위 Euclidean 오차."""
    if len(predicted) != len(expected):
        raise ValueError(
            f"predicted ({len(predicted)}) and expected ({len(expected)}) "
            f"must have the same length"
        )

    errors = []
    for (px, py), (ex, ey) in zip(predicted, expected):
        errors.append(float(np.hypot(float(px) - float(ex), float(py) - float(ey))))
    return errors


def summarize_errors_m(errors: Sequence[float]) -> Tuple[float, float]:
    """오차 목록의 (평균, p95)를 meter로 반환.

    p95는 `numpy.percentile(errors, 95, method="linear")`를 사용한다
    (docs/interfaces.md Homography 평가).
    """
    if not errors:
        raise ValueError("errors must not be empty")

    array = np.asarray(errors, dtype=np.float64)
    mean = float(array.mean())
    p95 = float(np.percentile(array, 95, method="linear"))
    return mean, p95
