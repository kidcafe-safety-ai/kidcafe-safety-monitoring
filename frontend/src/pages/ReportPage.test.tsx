import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { ApiResponse, EventListData } from "../api/eventsApi";
import { getEventsPage } from "../api/eventsApi";
import type { SafetyEvent } from "../types/event";
import type { SeoulInclusiveDateRange } from "../utils/eventDateTime";
import ReportPage, { loadAllEventsForReport } from "./ReportPage";

vi.mock("../api/eventsApi", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/eventsApi")>();

  return {
    ...actual,
    getEventsPage: vi.fn(),
  };
});

function event(id: string): SafetyEvent {
  return {
    event_id: id,
    timestamp: "00:00:01.000",
    event_type: "ENTER",
    track_id: 1,
    zone_id: "zone-a",
    created_at: "2026-08-07 00:00:00",
    bbox: [0, 0, 10, 10],
    foot_point: [5, 10],
    frame_number: 1,
    video_source: "camera-a",
  };
}

function page(
  items: SafetyEvent[],
  total: number,
  offset: number,
  limit = 100,
): ApiResponse<EventListData> {
  return {
    status: "success",
    data: {
      items,
      total,
      limit,
      offset,
      count: items.length,
    },
    message: null,
  };
}

const range: SeoulInclusiveDateRange = {
  createdFrom: "2026-08-07T00:00:00+09:00",
  createdTo: "2026-08-08T00:00:00+09:00",
  startDateKey: "2026-08-07",
  endDateKey: "2026-08-07",
  exclusiveEndDateKey: "2026-08-08",
  inclusiveDays: 1,
};

describe("loadAllEventsForReport", () => {
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("loads all pages with the requested Seoul date range", async () => {
    const firstPageEvents = Array.from({ length: 100 }, (_, index) =>
      event(`event-${index}`),
    );
    const secondPageEvents = [event("event-100")];
    const getEventsPageMock = vi.mocked(getEventsPage);
    getEventsPageMock
      .mockResolvedValueOnce(page(firstPageEvents, 101, 0))
      .mockResolvedValueOnce(page(secondPageEvents, 101, 100));

    const result = await loadAllEventsForReport(range, new AbortController().signal);

    expect(result.events).toHaveLength(101);
    expect(result.total).toBe(101);
    expect(getEventsPageMock).toHaveBeenNthCalledWith(
      1,
      {
        limit: 100,
        offset: 0,
        created_from: range.createdFrom,
        created_to: range.createdTo,
      },
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
  });

  it("does not report success when a later page fails", async () => {
    const firstPageEvents = Array.from({ length: 100 }, (_, index) =>
      event(`event-${index}`),
    );
    const getEventsPageMock = vi.mocked(getEventsPage);
    getEventsPageMock.mockResolvedValueOnce(page(firstPageEvents, 101, 0));
    getEventsPageMock.mockResolvedValueOnce({
      status: "error",
      data: { items: [], total: 0, limit: 100, offset: 100, count: 0 },
      message: "page failed",
    });

    await expect(
      loadAllEventsForReport(range, new AbortController().signal),
    ).rejects.toThrow("page failed");
  });

  it("does not report success when duplicate removal changes the reference total", async () => {
    const firstPageEvents = Array.from({ length: 100 }, (_, index) =>
      event(`event-${index}`),
    );
    const getEventsPageMock = vi.mocked(getEventsPage);
    getEventsPageMock
      .mockResolvedValueOnce(page(firstPageEvents, 101, 0))
      .mockResolvedValueOnce(page([event("event-99")], 101, 100));

    await expect(
      loadAllEventsForReport(range, new AbortController().signal),
    ).rejects.toThrow("조회 중 이벤트 목록이 변경되어 리포트를 완성할 수 없습니다.");
  });

  it("aborts before issuing a request when the signal is already cancelled", async () => {
    const controller = new AbortController();
    controller.abort();

    await expect(loadAllEventsForReport(range, controller.signal)).rejects.toThrow(
      "Aborted",
    );
    expect(getEventsPage).not.toHaveBeenCalled();
  });

  it("times out a stalled report and allows a successful empty retry", async () => {
    vi.useFakeTimers();
    const getEventsPageMock = vi.mocked(getEventsPage);
    getEventsPageMock
      .mockReturnValueOnce(new Promise(() => {}))
      .mockResolvedValueOnce(page([], 0, 0));
    render(<ReportPage />);
    fireEvent.click(screen.getByRole("button", { name: "안전 리포트 조회" }));
    await act(async () => { await vi.advanceTimersByTimeAsync(30000); });
    expect(screen.getByText(/리포트 조회 시간이 초과되었습니다/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "안전 리포트 조회" }));
    await act(async () => { await Promise.resolve(); });
    expect(screen.getByText("선택한 기간에 안전 이벤트가 없습니다.")).toBeInTheDocument();
  });
});
