export type AlertZoneType = "위험구역" | "주의구역" | "관찰구역";

export interface AlertZoneSetting {
  zone_id: string;
  zone_name: string;
  zone_type: AlertZoneType;
  dwell_threshold_sec: number;
  alert_enabled: boolean;
  points: [number, number][];
}
