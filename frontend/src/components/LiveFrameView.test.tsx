import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { getLiveFrame, isLiveFrameApiMode, type LiveFrameResult } from "../api/liveFrameApi";
import LiveFrameView from "./LiveFrameView";

vi.mock("../api/liveFrameApi", () => ({
  getLiveFrame: vi.fn(),
  isLiveFrameApiMode: vi.fn(() => true),
}));

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

const live = (): LiveFrameResult => ({
  status: "live",
  blob: new Blob(["jpeg"], { type: "image/jpeg" }),
  metadata: { source: null, frameNumber: null, capturedAt: null },
});
const empty: LiveFrameResult = {
  status: "empty",
  metadata: { source: null, frameNumber: null, capturedAt: null },
};

describe("LiveFrameView", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers();
    vi.mocked(isLiveFrameApiMode).mockReturnValue(true);
    vi.stubGlobal("URL", {
      ...URL,
      createObjectURL: vi.fn().mockReturnValue("blob:frame"),
      revokeObjectURL: vi.fn(),
    });
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  });

  it("reads the polling interval from Vite configuration", async () => {
    vi.stubEnv("VITE_LIVE_FRAME_POLL_INTERVAL_MS", "750");
    vi.mocked(getLiveFrame).mockResolvedValue(empty);
    render(<LiveFrameView />);
    await act(async () => { await Promise.resolve(); });
    await act(async () => { await vi.advanceTimersByTimeAsync(749); });
    expect(getLiveFrame).toHaveBeenCalledTimes(1);
    await act(async () => { await vi.advanceTimersByTimeAsync(1); });
    expect(getLiveFrame).toHaveBeenCalledTimes(2);
  });

  it("waits for a request to finish before scheduling the next one", async () => {
    const pending = deferred<LiveFrameResult>();
    vi.mocked(getLiveFrame).mockReturnValueOnce(pending.promise).mockResolvedValue(empty);
    render(<LiveFrameView pollIntervalMs={500} />);
    await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
    expect(getLiveFrame).toHaveBeenCalledTimes(1);
    await act(async () => { pending.resolve(live()); await pending.promise; });
    expect(screen.getByAltText("실시간 키즈카페 모니터링 화면")).toBeInTheDocument();
    await act(async () => { await vi.advanceTimersByTimeAsync(500); });
    expect(getLiveFrame).toHaveBeenCalledTimes(2);
    expect(screen.getByText(/이전 영상이 만료되었습니다/)).toBeInTheDocument();
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:frame");
  });

  it("ignores a timed out old frame after a newer 204 response", async () => {
    const old = deferred<LiveFrameResult>();
    vi.mocked(getLiveFrame).mockReturnValueOnce(old.promise).mockResolvedValue(empty);
    render(<LiveFrameView pollIntervalMs={500} />);
    await act(async () => { await vi.advanceTimersByTimeAsync(3500); });
    expect(getLiveFrame).toHaveBeenCalledTimes(2);
    expect(screen.getByText("카메라 연결을 기다리고 있습니다.")).toBeInTheDocument();
    await act(async () => { old.resolve(live()); await old.promise; });
    expect(screen.queryByAltText("실시간 키즈카페 모니터링 화면")).not.toBeInTheDocument();
    expect(URL.createObjectURL).not.toHaveBeenCalled();
  });

  it("cleans up on unmount and recovers after an API error", async () => {
    vi.mocked(getLiveFrame)
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce(live());
    const view = render(<LiveFrameView pollIntervalMs={500} />);
    await act(async () => { await Promise.resolve(); });
    expect(screen.getByText(/불러오지 못했습니다/)).toBeInTheDocument();
    await act(async () => { await vi.advanceTimersByTimeAsync(500); });
    expect(screen.getByAltText("실시간 키즈카페 모니터링 화면")).toBeInTheDocument();
    view.unmount();
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:frame");
    await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
    expect(getLiveFrame).toHaveBeenCalledTimes(2);
  });
});
