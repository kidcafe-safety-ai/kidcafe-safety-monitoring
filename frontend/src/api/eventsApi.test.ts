import { afterEach, describe, expect, it, vi } from "vitest";
import type { SafetyEvent } from "../types/event";

function apiEvent(overrides: Partial<SafetyEvent> = {}) {
  return {
    event_id: "api-event-1",
    timestamp: "00:00:01.000",
    event_type: "ENTER",
    track_id: 1,
    zone_id: "zone-a",
    created_at: "2026-08-07 00:00:00",
    bbox: [0, 0, 10, 10],
    foot_point: [5, 10],
    frame_number: 1,
    video_source: "api-camera",
    ...overrides,
  };
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

async function importEventsApi(mode: "api" | "mock" = "api") {
  vi.resetModules();
  vi.stubEnv("VITE_API_MODE", mode);
  vi.stubEnv("VITE_API_BASE_URL", "http://api.test");

  return import("./eventsApi");
}

describe("eventsApi", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("uses mock data only in mock mode", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const { getEvents } = await importEventsApi("mock");

    const response = await getEvents();

    expect(response.status).toBe("success");
    expect(response.data.length).toBeGreaterThan(0);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("uses API data in api mode", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse({
          status: "success",
          data: [apiEvent({ event_id: "real-api-event" })],
          message: null,
        }),
      ),
    );
    const { getEvents } = await importEventsApi("api");

    const response = await getEvents();

    expect(response.status).toBe("success");
    expect(response.data).toHaveLength(1);
    expect(response.data[0].event_id).toBe("real-api-event");
  });

  it("does not expose mock events when API mode request fails", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({}, 500)));
    const { getEvents } = await importEventsApi("api");

    const response = await getEvents();

    expect(response.status).toBe("error");
    expect(response.data).toEqual([]);
    expect(response.message).toContain("500");
  });

  it("distinguishes a successful empty response from an API error", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse({ status: "success", data: [], message: null }),
      ),
    );
    const { getEvents } = await importEventsApi("api");

    const response = await getEvents();

    expect(response).toMatchObject({
      status: "success",
      data: [],
      message: null,
    });
  });

  it("treats malformed event list responses as errors", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse({
          status: "success",
          data: { unexpected: "shape" },
          message: null,
        }),
      ),
    );
    const { getEvents } = await importEventsApi("api");

    const response = await getEvents();

    expect(response.status).toBe("error");
    expect(response.data).toEqual([]);
    expect(response.message).toBe("Event list response format was invalid");
  });

  it("encodes GET /events query parameters safely", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        status: "success",
        data: { items: [], total: 0, limit: 100, offset: 0, count: 0 },
        message: null,
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const { getEventsPage } = await importEventsApi("api");

    const response = await getEventsPage({
      limit: 100,
      offset: 0,
      event_type: "FALL_SUSPECT",
      zone_id: "zone/a",
      created_from: "2026-08-07T00:00:00+09:00",
      created_to: "2026-08-08T00:00:00+09:00",
    });

    const requestedUrl = String(fetchMock.mock.calls[0][0]);
    expect(response.status).toBe("success");
    expect(requestedUrl).toContain("event_type=FALL_SUSPECT");
    expect(requestedUrl).toContain("zone_id=zone%2Fa");
    expect(requestedUrl).toContain(
      "created_from=2026-08-07T00%3A00%3A00%2B09%3A00",
    );
    expect(requestedUrl).toContain(
      "created_to=2026-08-08T00%3A00%3A00%2B09%3A00",
    );
  });
});
