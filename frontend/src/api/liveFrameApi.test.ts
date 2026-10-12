import { afterEach, describe, expect, it, vi } from "vitest";

async function importApi(mode: "api" | "mock" = "api") {
  vi.resetModules();
  vi.stubEnv("VITE_API_MODE", mode);
  vi.stubEnv("VITE_API_BASE_URL", "http://api.test");
  return import("./liveFrameApi");
}

describe("liveFrameApi", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("returns an empty state for a bodyless 204 without using mock data", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);
    const { getLiveFrame } = await importApi();
    expect(await getLiveFrame()).toMatchObject({ status: "empty" });
    expect(fetchMock).toHaveBeenCalledWith("http://api.test/live/frame", expect.objectContaining({ cache: "no-store" }));
  });

  it("accepts JPEG 200 and rejects a malformed success response", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(new Blob(["jpeg"], { type: "image/jpeg" }), {
        status: 200, headers: { "Content-Type": "image/jpeg", "X-Source": "camera-1" },
      }))
      .mockResolvedValueOnce(new Response("text", { status: 200, headers: { "Content-Type": "text/plain" } }));
    vi.stubGlobal("fetch", fetchMock);
    const { getLiveFrame } = await importApi();
    expect(await getLiveFrame()).toMatchObject({ status: "live", metadata: { source: "camera-1" } });
    await expect(getLiveFrame()).rejects.toThrow("not JPEG");
  });

  it("never fetches or supplies a frame in mock mode", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const { getLiveFrame } = await importApi("mock");
    expect(await getLiveFrame()).toMatchObject({ status: "disabled" });
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
