import type { AlertZoneSetting } from "../types/zoneSettings";

export const mockZoneSettings: AlertZoneSetting[] = [
  {
    zone_id: "exit_area",
    zone_name: "출입구 위험구역",
    zone_type: "위험구역",
    dwell_threshold_sec: 10,
    alert_enabled: true,
    points: [
      [72, 18],
      [94, 20],
      [92, 52],
      [70, 48],
    ],
  },
  {
    zone_id: "slide_zone",
    zone_name: "미끄럼틀 주의구역",
    zone_type: "주의구역",
    dwell_threshold_sec: 15,
    alert_enabled: true,
    points: [
      [12, 55],
      [42, 50],
      [48, 78],
      [16, 86],
    ],
  },
  {
    zone_id: "play_area",
    zone_name: "일반 놀이구역",
    zone_type: "관찰구역",
    dwell_threshold_sec: 0,
    alert_enabled: false,
    points: [
      [50, 56],
      [78, 58],
      [82, 88],
      [52, 90],
    ],
  },
];
