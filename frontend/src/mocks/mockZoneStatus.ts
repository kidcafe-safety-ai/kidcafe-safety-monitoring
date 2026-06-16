import type { ZoneStatus } from "../types/event";

export const mockZoneStatus: ZoneStatus[] = [
  {
    zone_id: "exit_area",
    zone_name: "출입구 위험구역",
    current_count: 2,
    zone_type: "exit",
    risk_level: "HIGH",
  },
  {
    zone_id: "slide_zone",
    zone_name: "미끄럼틀 구역",
    current_count: 1,
    zone_type: "slide",
    risk_level: "NORMAL",
  },
];
