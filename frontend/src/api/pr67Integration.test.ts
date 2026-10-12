import { describe, expect, it, vi } from "vitest";

const baseUrl = process.env.PR67_API_URL;

describe.skipIf(!baseUrl)("PR #67 running Backend contract", () => {
  it("reads empty status/events, configured zones, bodyless frame, and save errors", async () => {
    vi.resetModules();
    vi.stubEnv("VITE_API_MODE", "api");
    vi.stubEnv("VITE_API_BASE_URL", baseUrl);
    try {
      const [{ getCurrentStatus, getEventsPage }, { getZones, putZones }, { getLiveFrame }] =
        await Promise.all([
          import("./eventsApi"),
          import("./zoneSettingsApi"),
          import("./liveFrameApi"),
        ]);
      expect(await getCurrentStatus()).toMatchObject({
        status: "success",
        data: { active_track_count: 0, updated_at: null },
      });
      expect(await getEventsPage({
        limit: 10,
        offset: 0,
        created_from: "2026-10-12T00:00:00+09:00",
        created_to: "2026-10-13T00:00:00+09:00",
      })).toMatchObject({
        status: "success",
        data: { items: [], total: 0, limit: 10, offset: 0 },
      });
      const zones = await getZones();
      expect(zones.status).toBe("success");
      expect(zones.data?.zones.length).toBeGreaterThan(0);
      expect(await getLiveFrame()).toMatchObject({ status: "empty" });
      expect(await putZones({
        expected_version: `sha256:${"0".repeat(64)}`,
        zones: zones.data!.zones,
      })).toMatchObject({ status: "error", error_type: "conflict", status_code: 409 });
      expect(await putZones({
        expected_version: zones.data!.version,
        zones: [{ ...zones.data!.zones[0], zone_name: "" }],
      })).toMatchObject({ status: "error", error_type: "validation", status_code: 422 });
    } finally {
      vi.unstubAllEnvs();
    }
  });
});
