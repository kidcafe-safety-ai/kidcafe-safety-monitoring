export type EventType =
  | "ENTER"
  | "DWELL"
  | "EXIT"
  | "ENTER_RESTRICTED"
  | "DANGER_ZONE_DWELL"
  | "FALL_SUSPECT";

export type Severity = "LOW" | "MEDIUM" | "HIGH";

export type CurrentRiskLevel = "NORMAL" | "HIGH";

export type ZoneType = "exit" | "play" | "restricted" | "danger";

export type EventCauseType = "NEARBY_TRACK";

export interface EventCauseEvidence {
  min_distance_norm: number;
  closing_speed_norm: number;
  time_to_fall_sec: number;
}

export interface EventCause {
  type: EventCauseType;
  track_id: number;
  score: number;
  evidence: EventCauseEvidence;
}

export interface SafetyEvent {
  event_id: string;
  timestamp: string;
  event_type: EventType;
  track_id: number;
  zone_id: string;

  created_at?: string;
  event_label?: string;
  severity?: Severity;
  zone_name?: string;
  zone_type?: ZoneType;

  event_confidence?: number | null;
  cause?: EventCause | null;

  bbox: [number, number, number, number];
  foot_point: [number, number];

  frame_number: number;
  video_source: string;
}

export interface DashboardSummary {
  active_tracks: number;
  today_event_count: number | null;
  danger_zone_occupancy: number;
  recent_event_count: number | null;
}

export interface ZoneStatus {
  zone_id: string;
  zone_name: string;
  current_count: number;
  zone_type?: ZoneType;
  risk_level?: CurrentRiskLevel;
}
