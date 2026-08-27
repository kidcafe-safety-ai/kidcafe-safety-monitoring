import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { SafetyEvent } from "../types/event";
import RecentEventList from "./RecentEventList";

function highEvent(id: string): SafetyEvent {
  return {
    event_id: id,
    timestamp: "00:00:01.000",
    event_type: "FALL_SUSPECT",
    track_id: 7,
    zone_id: "__global__",
    created_at: "2026-08-07 00:00:00",
    severity: "HIGH",
    bbox: [0, 0, 10, 10],
    foot_point: [5, 10],
    frame_number: 1,
    video_source: "camera-a",
  };
}

describe("RecentEventList", () => {
  it("does not highlight existing high events after initial API error recovery", () => {
    const { rerender } = render(
      <RecentEventList events={[]} hasError isLoading={false} />,
    );

    expect(screen.getByText("최근 안전 이벤트를 불러오지 못했습니다. 연결 상태를 확인해 주세요.")).toBeInTheDocument();

    rerender(
      <RecentEventList
        events={[highEvent("fall-1")]}
        hasError={false}
        isLoading={false}
      />,
    );

    expect(
      screen.getByRole("button", { name: "낙상 의심 이벤트 상세 보기" }),
    ).not.toHaveClass("high-event-highlight");
  });

  it("highlights only newly observed high events after the baseline is initialized", () => {
    const { rerender } = render(
      <RecentEventList
        events={[highEvent("fall-1")]}
        hasError={false}
        isLoading={false}
      />,
    );

    rerender(
      <RecentEventList
        events={[highEvent("fall-2"), highEvent("fall-1")]}
        hasError={false}
        isLoading={false}
      />,
    );

    const [newEvent, existingEvent] = screen.getAllByRole("button", {
      name: "낙상 의심 이벤트 상세 보기",
    });

    expect(newEvent).toHaveClass("high-event-highlight");
    expect(existingEvent).not.toHaveClass("high-event-highlight");
  });
});
