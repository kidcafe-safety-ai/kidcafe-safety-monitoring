import { mockZoneConfig } from "../mocks/mockZoneSettings";
import type { ZoneApiResponse, ZoneConfig } from "../types/zoneSettings";

function cloneZoneConfig(config: ZoneConfig): ZoneConfig {
  return {
    ...config,
    zones: config.zones.map((zone) => ({
      ...zone,
      points: zone.points.map(([x, y]) => [x, y]),
      rules: { ...zone.rules },
    })),
  };
}

// Development fixture only. API mode must use GET /zones and PUT /zones.
export async function getMockZoneSettings(): Promise<ZoneApiResponse<ZoneConfig>> {
  return {
    status: "success",
    data: cloneZoneConfig(mockZoneConfig),
    message: null,
  };
}
