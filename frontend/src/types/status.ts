import type { CurrentRiskLevel } from "./event";

export interface ZoneOccupancy {
  zone_id: string;
  zone_name: string;
  current_count: number;
  risk_level: CurrentRiskLevel;
}

export interface CurrentStatus {
  source: string;
  frame_number: number;
  active_track_count: number;
  zone_occupancy: ZoneOccupancy[];
  updated_at: string | null;
}
