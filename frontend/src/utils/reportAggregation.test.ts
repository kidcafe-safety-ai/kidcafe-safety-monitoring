import { describe, expect, it } from "vitest";
import type { SafetyEvent } from "../types/event";
import { aggregateReportEvents } from "./reportAggregation";

function event(overrides: Partial<SafetyEvent>): SafetyEvent {
  return {
    event_id: "event-1",
    timestamp: "00:00:01.000",
    event_type: "ENTER",
    track_id: 1,
    zone_id: "zone-a",
    created_at: "2026-08-07 00:00:00",
    zone_name: "놀이구역",
    zone_type: "play",
    bbox: [0, 0, 10, 10],
    foot_point: [5, 10],
    frame_number: 1,
    video_source: "camera-a",
    ...overrides,
  };
}

describe("reportAggregation", () => {
  it("aggregates Phase 4 report counts without inventing backend fields", () => {
    const result = aggregateReportEvents([
      event({ event_id: "enter-1", event_type: "ENTER", severity: "MEDIUM" }),
      event({
        event_id: "fall-1",
        event_type: "FALL_SUSPECT",
        zone_id: "__global__",
        zone_name: undefined,
        zone_type: undefined,
        cause: null,
      }),
      event({
        event_id: "danger-1",
        event_type: "DANGER_ZONE_DWELL",
        zone_id: "danger-a",
        zone_name: "위험구역 A",
        zone_type: "danger",
      }),
      event({
        event_id: "unknown-1",
        event_type: "NEW_EVENT_TYPE" as SafetyEvent["event_type"],
        zone_id: "",
        zone_name: undefined,
      }),
    ]);

    expect(result.totalEvents).toBe(4);
    expect(result.fallSuspectCount).toBe(1);
    expect(result.highSeverityCount).toBe(2);
    expect(result.dangerZoneEventCount).toBe(1);
    expect(result.eventTypeCounts).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ eventType: "ENTER", count: 1, label: "진입" }),
        expect.objectContaining({
          eventType: "FALL_SUSPECT",
          count: 1,
          label: "낙상 의심",
        }),
        expect.objectContaining({
          eventType: "NEW_EVENT_TYPE",
          count: 1,
          label: "알 수 없는 이벤트",
        }),
      ]),
    );
    expect(result.zoneCounts).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ zoneKey: "zone-a", label: "놀이구역", count: 1 }),
        expect.objectContaining({
          zoneKey: "__global__",
          label: "전체 구역",
          count: 1,
        }),
        expect.objectContaining({
          zoneKey: "Zone 정보 없음",
          label: "Zone 정보 없음",
          count: 1,
        }),
      ]),
    );
    expect(result.fallSuspectItems).toEqual([
      expect.objectContaining({
        eventId: "fall-1",
        trackLabel: "Track #1",
        causeText: "원인 후보 없음",
      }),
    ]);
  });

  it("deduplicates duplicate event_id before calculating report totals", () => {
    const result = aggregateReportEvents([
      event({ event_id: "same-id", event_type: "ENTER" }),
      event({ event_id: "same-id", event_type: "FALL_SUSPECT" }),
    ]);

    expect(result.totalEvents).toBe(1);
    expect(result.fallSuspectCount).toBe(0);
    expect(result.eventTypeCounts).toEqual([
      expect.objectContaining({ eventType: "ENTER", count: 1 }),
    ]);
  });

  it("summarizes FALL_SUSPECT cause candidates when present", () => {
    const result = aggregateReportEvents([
      event({
        event_id: "fall-with-cause",
        event_type: "FALL_SUSPECT",
        cause: {
          type: "NEARBY_TRACK",
          track_id: 9,
          score: 0.8,
          evidence: {
            min_distance_norm: 0.1,
            closing_speed_norm: 0.2,
            time_to_fall_sec: 0.3,
          },
        },
      }),
    ]);

    expect(result.fallSuspectItems[0]).toMatchObject({
      eventId: "fall-with-cause",
      causeText: "외부 접촉 의심 · Track #9",
    });
  });
});
