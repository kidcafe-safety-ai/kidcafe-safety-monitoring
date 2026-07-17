import type { EventType } from "./event";

export type AlertSeverity = "HIGH" | "MEDIUM" | "LOW";
export type AlertStatus = "미확인" | "확인중" | "처리완료";

export interface AlertHistoryItem {
  alert_id: string;
  occurred_at: string;
  title: string;
  zone_id: string;
  zone_name: string;
  target: string;
  severity: AlertSeverity;
  status: AlertStatus;
  event_type: EventType;
  message: string;
  action_note: string;
  cause_text?: string;
}
