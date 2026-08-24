import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  getCurrentStatus,
  getDashboardSummary,
  getRecentEvents,
} from "../api/eventsApi";
import type { DashboardSummary, SafetyEvent } from "../types/event";
import type { CurrentStatus } from "../types/status";
import MonitoringPage from "./MonitoringPage";

vi.mock("../api/eventsApi", () => ({
  RECENT_EVENT_LIMIT: 5,
  getCurrentStatus: vi.fn(),
  getDashboardSummary: vi.fn(),
  getRecentEvents: vi.fn(),
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
  default: () => <div data-testid="zone-status-panel" />,
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
    vi.useFakeTimers();
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
