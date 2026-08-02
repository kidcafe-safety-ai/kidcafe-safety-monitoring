import type { ZoneConfig } from "../types/zoneSettings";

export const mockZoneConfig: ZoneConfig = {
  version: "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  updated_at: "2026-08-07T01:30:00Z",
  zones: [
    {
      zone_id: "danger_door",
      zone_name: "출입문 위험구역",
      type: "polygon",
      zone_type: "danger",
      points: [
        [0.1, 0.2],
        [0.32, 0.2],
        [0.32, 0.52],
        [0.1, 0.52],
      ],
      rules: {
        enter_alert: true,
        dwell_threshold_sec: 5,
      },
    },
    {
      zone_id: "slide_restricted",
      zone_name: "미끄럼틀 하단 제한구역",
      type: "polygon",
      zone_type: "restricted",
      points: [
        [0.55, 0.58],
        [0.86, 0.58],
        [0.82, 0.9],
        [0.52, 0.86],
      ],
      rules: {
        enter_alert: true,
        dwell_threshold_sec: 3,
      },
    },
  ],
};
