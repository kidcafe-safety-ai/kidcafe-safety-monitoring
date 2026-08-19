import { afterEach, describe, expect, it, vi } from "vitest";

const VALID_VERSION = `sha256:${"a".repeat(64)}`;

function zoneConfig(overrides: Record<string, unknown> = {}) {
  return {
    version: VALID_VERSION,
    updated_at: "2026-08-07T00:00:00Z",
    zones: [],
    ...overrides,
  };
}

function envelope(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

async function importZoneSettingsApi(mode: "api" | "mock" = "api") {
  vi.resetModules();
  vi.stubEnv("VITE_API_MODE", mode);
  vi.stubEnv("VITE_API_BASE_URL", "http://api.test");

  return import("./zoneSettingsApi");
}

describe("zoneSettingsApi", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("uses mock zones only in mock mode", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const { getZones } = await importZoneSettingsApi("mock");

    const response = await getZones();

    expect(response.status).toBe("success");
    expect(response.data?.zones.length).toBeGreaterThan(0);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("returns successful empty zones from API mode without falling back to mock", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        envelope({
          status: "success",
          data: zoneConfig({ zones: [] }),
          message: null,
        }),
      ),
    );
    const { getZones } = await importZoneSettingsApi("api");

    const response = await getZones();

    expect(response.status).toBe("success");
    expect(response.data?.zones).toEqual([]);
  });

  it("fails closed when API mode cannot load zones", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        envelope(
          {
            status: "error",
            data: null,
            message: "zone configuration is unavailable",
          },
          500,
        ),
      ),
    );
    const { getZones } = await importZoneSettingsApi("api");

    const response = await getZones();

    expect(response).toMatchObject({
      status: "error",
      data: null,
      error_type: "server",
      message: "zone configuration is unavailable",
    });
  });

  it("preserves conflict messages from PUT /zones", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        envelope(
          {
            status: "error",
            data: null,
            message: "zone configuration version conflict",
          },
          409,
        ),
      ),
    );
    const { putZones } = await importZoneSettingsApi("api");

    const response = await putZones({
      expected_version: VALID_VERSION,
      zones: [],
    });

    expect(response).toMatchObject({
      status: "error",
      data: null,
      error_type: "conflict",
      message: "zone configuration version conflict",
    });
  });

  it("collects validation details from 422 responses", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        envelope(
          {
            detail: [
              {
                loc: ["body", "zones", 0, "points"],
                msg: "points must contain at least 3 points",
              },
            ],
          },
          422,
        ),
      ),
    );
    const { putZones } = await importZoneSettingsApi("api");

    const response = await putZones({
      expected_version: VALID_VERSION,
      zones: [],
    });

    expect(response.status).toBe("error");
    expect(response.error_type).toBe("validation");
    expect(response.details).toEqual(["points must contain at least 3 points"]);
  });
});
