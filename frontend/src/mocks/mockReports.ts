import type { SafetyReport } from "../types/report";

export const mockReports: SafetyReport[] = [
  {
    report_id: "report-20260514-today",
    report_date: "2026-05-14",
    report_type: "오늘 리포트",
    child_group: "오늘 방문 어린이",
    period_start: "2026-05-14 10:00",
    period_end: "2026-05-14 12:30",
    summary_title: "오늘의 놀이 리포트",
    total_events: 12,
    high_risk_events: 2,
    dwell_events: 5,
    enter_events: 5,
    exit_events: 2,
    top_zones: [
      { zone_name: "볼풀존", event_count: 5 },
      { zone_name: "트램폴린존", event_count: 4 },
      { zone_name: "제한구역 A", event_count: 2 },
    ],
    safety_note:
      "볼풀존과 트램폴린존 이용이 많았고, 제한구역 접근은 직원 확인 후 안전하게 안내되었습니다.",
    recommended_action:
      "보호자에게 주요 활동 구역과 직원 확인 완료 내용을 함께 공유하는 것을 권장합니다.",
    generated_at: "2026-05-14 12:42",
    share_target: "보호자 공유용",
  },
  {
    report_id: "report-20260514-weekly",
    report_date: "2026-05-14",
    report_type: "주간 리포트",
    child_group: "햇살반",
    period_start: "2026-05-08",
    period_end: "2026-05-14",
    summary_title: "햇살반 주간 안전 요약",
    total_events: 36,
    high_risk_events: 4,
    dwell_events: 14,
    enter_events: 17,
    exit_events: 5,
    top_zones: [
      { zone_name: "트램폴린존", event_count: 13 },
      { zone_name: "입구 관찰구역", event_count: 9 },
      { zone_name: "볼풀존", event_count: 8 },
    ],
    safety_note:
      "주중 트램폴린존 이용 비중이 높았습니다. 직원 안내 후 위험 알림은 모두 처리되었습니다.",
    recommended_action:
      "활동량이 높은 시간대에는 트램폴린존 주변 안내 인력을 유지하는 것이 좋습니다.",
    generated_at: "2026-05-14 18:10",
    share_target: "운영자 확인용",
  },
  {
    report_id: "report-20260514-zone",
    report_date: "2026-05-14",
    report_type: "구역 리포트",
    child_group: "전체 어린이",
    period_start: "2026-05-14 09:00",
    period_end: "2026-05-14 18:00",
    summary_title: "제한구역 A 집중 리포트",
    total_events: 8,
    high_risk_events: 3,
    dwell_events: 4,
    enter_events: 4,
    exit_events: 0,
    top_zones: [
      { zone_name: "제한구역 A", event_count: 8 },
      { zone_name: "입구 관찰구역", event_count: 2 },
    ],
    safety_note:
      "제한구역 A 근처 접근이 반복되었습니다. 모든 알림은 직원 확인 또는 안내 조치로 마무리되었습니다.",
    recommended_action:
      "해당 구역 안내 표식을 강화하고 체류 기준 시간을 다시 점검하는 것을 권장합니다.",
    generated_at: "2026-05-14 18:25",
    share_target: "매장 관리자",
  },
  {
    report_id: "report-20260513-afternoon",
    report_date: "2026-05-13",
    report_type: "오늘 리포트",
    child_group: "오후 이용 어린이",
    period_start: "2026-05-13 14:00",
    period_end: "2026-05-13 17:30",
    summary_title: "오후 놀이 안전 리포트",
    total_events: 9,
    high_risk_events: 1,
    dwell_events: 3,
    enter_events: 4,
    exit_events: 2,
    top_zones: [
      { zone_name: "볼풀존", event_count: 4 },
      { zone_name: "수유실 앞", event_count: 3 },
      { zone_name: "퇴장 게이트", event_count: 2 },
    ],
    safety_note:
      "오후 시간대에는 볼풀존 이용이 많았으며, 퇴장 게이트 이동은 보호자 동행 확인 후 마감되었습니다.",
    recommended_action:
      "보호자에게 놀이 시간과 안전 확인 내용을 간단히 공유하면 좋습니다.",
    generated_at: "2026-05-13 17:45",
    share_target: "보호자 공유용",
  },
];
