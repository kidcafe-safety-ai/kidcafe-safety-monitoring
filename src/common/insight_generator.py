"""
룰 기반 인사이트 생성 모듈.

담당 기능:
- 대시보드 인사이트 카드에 표시할 문장 생성
"""

from __future__ import annotations

from typing import Any, Dict, List

from src.common.event_counter import (
    calculate_summary_kpi,
    count_events_by_type,
    count_events_by_zone,
)
from src.common.types import Event


def generate_insights(events: List[Event | Dict[str, Any]]) -> List[str]:
    """
    이벤트 목록을 기반으로 룰 기반 인사이트 문장을 생성한다.

    Returns:
        인사이트 문장 리스트
    """
    if not events:
        return ["아직 분석할 이벤트가 없습니다."]

    insights: List[str] = []

    summary = calculate_summary_kpi(events)
    type_counts = count_events_by_type(events)
    zone_counts = count_events_by_zone(events)

    total_events = summary["total_events"]

    if total_events == 0:
        return ["아직 분석할 이벤트가 없습니다."]

    if zone_counts:
        top_zone, top_count = max(zone_counts.items(), key=lambda item: item[1])
        top_zone_ratio = round((top_count / total_events) * 100, 1)

        insights.append(
            f"{top_zone} 구역에서 전체 이벤트의 {top_zone_ratio}%가 발생했습니다."
        )

    dwell_count = type_counts.get("DWELL", 0)

    if dwell_count > 0:
        dwell_ratio = round((dwell_count / total_events) * 100, 1)

        insights.append(
            f"체류 위험(DWELL) 이벤트가 전체 이벤트의 {dwell_ratio}%를 차지합니다."
        )

    enter_count = type_counts.get("ENTER", 0)
    exit_count = type_counts.get("EXIT", 0)

    if exit_count > 0 and enter_count > exit_count * 1.5:
        insights.append(
            "진입 이벤트가 이탈 이벤트보다 많아 특정 구역에 머무는 인원이 있을 수 있습니다."
        )

    avg_dwell_seconds = float(summary.get("avg_dwell_seconds", 0.0))

    if avg_dwell_seconds >= 10:
        insights.append(
            f"평균 체류 시간이 {avg_dwell_seconds}초로 높게 나타났습니다."
        )

    total_tracks = int(summary.get("total_tracks", 0))

    if total_tracks >= 5:
        insights.append(
            f"총 {total_tracks}명의 추적 ID가 감지되어 혼잡도가 높을 수 있습니다."
        )

    if not insights:
        insights.append("현재 이벤트 분포에서 특이 위험 패턴은 크게 보이지 않습니다.")

    return insights
