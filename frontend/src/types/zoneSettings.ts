export type ZoneType = "play" | "exit" | "restricted" | "danger";

export type ZonePoint = [number, number];

export interface ZoneRules {
  enter_alert: boolean;
  dwell_threshold_sec: number;
}

export interface Zone {
  zone_id: string;
  zone_name: string;
  type: "polygon";
  zone_type: ZoneType;
  points: ZonePoint[];
  rules: ZoneRules;
}

export interface ZoneConfig {
  version: string;
  updated_at: string;
  zones: Zone[];
}

export interface PutZonesRequest {
  expected_version: string;
  zones: Zone[];
}

export type ZoneApiErrorType =
  | "conflict"
  | "validation"
  | "server"
  | "network"
  | "schema"
  | "unknown";

export interface ZoneApiResponse<T> {
  status: "success" | "error";
  data: T | null;
  message: string | null;
  error_type?: ZoneApiErrorType;
  status_code?: number;
  details?: string[];
}
