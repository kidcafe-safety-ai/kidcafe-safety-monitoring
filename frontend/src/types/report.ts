export interface ReportTopZone {
  zone_name: string;
  event_count: number;
}

export type ReportType = "오늘 리포트" | "주간 리포트" | "구역 리포트";

export interface SafetyReport {
  report_id: string;
  report_date: string;
  report_type: ReportType;
  child_group: string;
  period_start: string;
  period_end: string;
  summary_title: string;
  total_events: number;
  high_risk_events: number;
  dwell_events: number;
  enter_events: number;
  exit_events: number;
  top_zones: ReportTopZone[];
  safety_note: string;
  recommended_action: string;
  generated_at: string;
  share_target: string;
}
