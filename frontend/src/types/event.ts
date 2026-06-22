export type EventType = "ENTER" | "DWELL" | "EXIT";

export type Severity = "LOW" | "MEDIUM" | "HIGH";

export type CurrentRiskLevel = "NORMAL" | "HIGH";

export type ZoneType = "exit" | "play" | "restricted" | "slide";

export interface SafetyEvent {
  event_id: string;
  timestamp: string;
  event_type: EventType;
  track_id: number;
  zone_id: string;

  event_label?: string;
  severity?: Severity;
  zone_type?: ZoneType;

  bbox: [number, number, number, number];
  foot_point: [number, number];

  frame_number: number;
  video_source: string;
}

export interface DashboardSummary {
  active_tracks: number;
  today_event_count: number;
  danger_zone_occupancy: number;
  recent_event_count: number;
}

export interface ZoneStatus {
  zone_id: string;
  zone_name: string;
  current_count: number;
  zone_type?: ZoneType;
  risk_level?: CurrentRiskLevel;
}
