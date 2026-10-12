import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  getCurrentStatus,
  getDashboardSummary,
  getRecentEvents,
} from "../api/eventsApi";
import { getZones } from "../api/zoneSettingsApi";
import type { DashboardSummary, SafetyEvent } from "../types/event";
import type { CurrentStatus } from "../types/status";
import MonitoringPage from "./MonitoringPage";

vi.mock("../api/eventsApi", () => ({
  RECENT_EVENT_LIMIT: 5,
  getCurrentStatus: vi.fn(),
  getDashboardSummary: vi.fn(),
  getRecentEvents: vi.fn(),
}));

vi.mock("../api/zoneSettingsApi", () => ({
  getZones: vi.fn(),
}));

vi.mock("../components/LiveFrameView", () => ({
  default: () => <div data-testid="live-frame-view" />,
}));

vi.mock("../components/RecentEventList", () => ({
  default: ({
    events,
    hasError,
    isLoading,
  }: {
    events: SafetyEvent[];
    hasError: boolean;
    isLoading: boolean;
  }) => (
    <div data-testid="recent-event-list">
      {isLoading ? "loading" : `${hasError ? "error" : "ok"}:${events.length}`}
    </div>
  ),
}));

vi.mock("../components/ZoneStatusPanel", () => ({
  default: ({ zones }: { zones: { zone_id: string; current_count: number }[] }) => (
    <div data-testid="zone-status-panel">
      {zones.map((zone) => `${zone.zone_id}:${zone.current_count}`).join(",")}
    </div>
  ),
}));

const POLLING_REQUEST_TIMEOUT_MS = 10000;
const INITIAL_DASHBOARD_RETRY_INTERVAL_MS = 3000;

function neverSettlingPromise<T>() {
  return new Promise<T>(() => {});
}

function summaryResponse(data: DashboardSummary) {
  return {
    status: "success" as const,
    data,
    message: null,
  };
}

function eventsResponse(data: SafetyEvent[]) {
  return {
    status: "success" as const,
    data,
    message: null,
  };
}

function currentStatusResponse(data: CurrentStatus) {
  return {
    status: "success" as const,
    data,
    message: null,
  };
}

const summary: DashboardSummary = {
  active_tracks: 0,
  today_event_count: 2,
  danger_zone_occupancy: 0,
  recent_event_count: 1,
};

const currentStatus: CurrentStatus = {
  source: "camera-a",
  frame_number: 100,
  active_track_count: 3,
  zone_occupancy: [],
  updated_at: "2026-08-24T00:00:00+09:00",
};

describe("MonitoringPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers();
    vi.mocked(getZones).mockResolvedValue({
      status: "success",
      data: { version: "sha256:test", updated_at: "2026-08-24T00:00:00Z", zones: [] },
      message: null,
    });
  });

  it("shows every configured zone at zero and accepts a later shutdown status", async () => {
    vi.mocked(getDashboardSummary).mockResolvedValue(summaryResponse(summary));
    vi.mocked(getRecentEvents).mockResolvedValue(eventsResponse([]));
    vi.mocked(getCurrentStatus)
      .mockResolvedValueOnce(currentStatusResponse(currentStatus))
      .mockResolvedValue(currentStatusResponse({
        ...currentStatus,
        active_track_count: 0,
        zone_occupancy: [],
        updated_at: null,
      }));
    vi.mocked(getZones).mockResolvedValue({
      status: "success",
      data: {
        version: "sha256:test",
        updated_at: "2026-08-24T00:00:00Z",
        zones: ["a", "b"].map((zone_id) => ({
          zone_id, zone_name: zone_id, type: "polygon" as const,
          zone_type: "danger" as const,
          points: [[0, 0], [1, 0], [0, 1]] as [number, number][],
          rules: { enter_alert: false, dwell_threshold_sec: 0 },
        })),
      },
      message: null,
    });

    render(<MonitoringPage />);
    await act(async () => { await Promise.resolve(); });
    expect(screen.getByTestId("zone-status-panel")).toHaveTextContent("a:0,b:0");
    await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
    expect(screen.getByText("현재 감지 인원").closest("section")).toHaveTextContent("0");
    expect(screen.getByTestId("zone-status-panel")).toHaveTextContent("a:0,b:0");
  });

  it("marks old KPI data as stale during a status outage and recovers", async () => {
    vi.mocked(getDashboardSummary).mockResolvedValue(summaryResponse(summary));
    vi.mocked(getRecentEvents).mockResolvedValue(eventsResponse([]));
    vi.mocked(getCurrentStatus)
      .mockResolvedValueOnce(currentStatusResponse(currentStatus))
      .mockResolvedValueOnce(currentStatusResponse(currentStatus))
      .mockResolvedValueOnce({
        status: "error", data: currentStatus, message: "offline",
      })
      .mockResolvedValue(currentStatusResponse({ ...currentStatus, active_track_count: 0 }));
    render(<MonitoringPage />);
    await act(async () => { await Promise.resolve(); });
    await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
    expect(screen.getByText(/마지막 정상 응답의 오래된 데이터/)).toBeInTheDocument();
    expect(screen.getByText("현재 감지 인원").closest("section")).toHaveTextContent("3");
    await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
    expect(screen.queryByText(/마지막 정상 응답의 오래된 데이터/)).not.toBeInTheDocument();
    expect(screen.getByText("현재 감지 인원").closest("section")).toHaveTextContent("0");
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("retries the initial dashboard request after the polling watchdog timeout", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    const dashboardSummaryMock = vi.mocked(getDashboardSummary);
    const recentEventsMock = vi.mocked(getRecentEvents);
    const currentStatusMock = vi.mocked(getCurrentStatus);

    dashboardSummaryMock
      .mockReturnValueOnce(neverSettlingPromise())
      .mockResolvedValue(summaryResponse(summary));
    recentEventsMock
      .mockReturnValueOnce(neverSettlingPromise())
      .mockResolvedValue(eventsResponse([]));
    currentStatusMock
      .mockReturnValueOnce(neverSettlingPromise())
      .mockResolvedValue(currentStatusResponse(currentStatus));

    render(<MonitoringPage />);

    expect(screen.getByText("데이터를 불러오는 중입니다.")).toBeInTheDocument();
    expect(dashboardSummaryMock).toHaveBeenCalledTimes(1);
    expect(recentEventsMock).toHaveBeenCalledTimes(1);
    expect(currentStatusMock).toHaveBeenCalledTimes(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(
        POLLING_REQUEST_TIMEOUT_MS + INITIAL_DASHBOARD_RETRY_INTERVAL_MS,
      );
    });

    expect(dashboardSummaryMock.mock.calls.length).toBeGreaterThanOrEqual(2);
    expect(recentEventsMock.mock.calls.length).toBeGreaterThanOrEqual(2);
    expect(currentStatusMock.mock.calls.length).toBeGreaterThanOrEqual(2);
    expect(screen.queryByText("데이터를 불러오는 중입니다.")).not.toBeInTheDocument();
    expect(screen.getByTestId("recent-event-list")).toHaveTextContent("ok:0");
  });
});
