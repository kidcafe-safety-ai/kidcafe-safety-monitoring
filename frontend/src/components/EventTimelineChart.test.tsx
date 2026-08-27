import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { SafetyEvent } from "../types/event";
import EventTimelineChart from "./EventTimelineChart";

function event(overrides: Partial<SafetyEvent>): SafetyEvent {
  return {
    event_id: "event-1",
    timestamp: "00:00:01.000",
    event_type: "ENTER",
    track_id: 1,
    zone_id: "zone-a",
    created_at: "2026-08-07 00:00:00",
    bbox: [0, 0, 10, 10],
    foot_point: [5, 10],
    frame_number: 1,
    video_source: "camera-a",
    ...overrides,
  };
}

describe("EventTimelineChart", () => {
  it("groups timeline buckets by created_at instead of video-relative timestamp", () => {
    render(
      <EventTimelineChart
        events={[
          event({
            event_id: "session-a-event",
            timestamp: "00:00:01.000",
            created_at: "2026-08-07 16:00:01",
          }),
          event({
            event_id: "session-b-event",
            timestamp: "00:00:01.000",
            created_at: "2026-08-07 17:00:01",
          }),
        ]}
      />,
    );

    expect(
      screen.getByLabelText("시간대별 이벤트 발생 추이"),
    ).toBeInTheDocument();
    expect(screen.getByText("01:00:00~01:00:10: 1건")).toBeInTheDocument();
    expect(screen.getByText("02:00:00~02:00:10: 1건")).toBeInTheDocument();
  });

  it("shows an empty state when no event has a parseable created_at", () => {
    render(
      <EventTimelineChart
        events={[
          event({
            event_id: "invalid-created-at",
            created_at: "not-a-date",
          }),
        ]}
      />,
    );

    expect(screen.getByText("표시할 이벤트 데이터가 없습니다.")).toBeInTheDocument();
  });
});
