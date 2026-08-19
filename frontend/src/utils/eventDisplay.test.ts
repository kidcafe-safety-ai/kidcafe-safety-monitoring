import { describe, expect, it } from "vitest";
import type { EventCause } from "../types/event";
import {
  formatEventCause,
  getEventDisplayMeta,
  getEventSeverity,
  KNOWN_EVENT_TYPES,
} from "./eventDisplay";

describe("eventDisplay", () => {
  it("defines display metadata for all known Phase 4 event types", () => {
    expect(KNOWN_EVENT_TYPES).toEqual([
      "ENTER",
      "DWELL",
      "EXIT",
      "ENTER_RESTRICTED",
      "DANGER_ZONE_DWELL",
      "FALL_SUSPECT",
    ]);

    expect(getEventDisplayMeta("ENTER")).toMatchObject({
      label: "진입",
      severity: "LOW",
      badgeClass: "type-enter",
    });
    expect(getEventDisplayMeta("DWELL")).toMatchObject({
      label: "체류",
      severity: "LOW",
    });
    expect(getEventDisplayMeta("EXIT")).toMatchObject({
      label: "이탈",
      severity: "LOW",
    });
    expect(getEventDisplayMeta("ENTER_RESTRICTED")).toMatchObject({
      label: "제한구역 진입",
      severity: "HIGH",
    });
    expect(getEventDisplayMeta("DANGER_ZONE_DWELL")).toMatchObject({
      label: "위험구역 체류",
      severity: "HIGH",
    });
    expect(getEventDisplayMeta("FALL_SUSPECT")).toMatchObject({
      label: "낙상 의심",
      severity: "HIGH",
    });
  });

  it("uses event type severity before payload fallback for known events", () => {
    expect(getEventSeverity("ENTER", "MEDIUM")).toBe("LOW");
    expect(getEventSeverity("UNKNOWN_EVENT", "MEDIUM")).toBe("MEDIUM");
  });

  it("keeps unknown event types visible without pretending they are known", () => {
    expect(getEventDisplayMeta("UNKNOWN_EVENT")).toMatchObject({
      type: "UNKNOWN_EVENT",
      label: "알 수 없는 이벤트",
      severity: null,
      badgeClass: "type-unknown",
    });
  });

  it("formats FALL_SUSPECT cause as an external contact suspicion only", () => {
    const cause: EventCause = {
      type: "NEARBY_TRACK",
      track_id: 42,
      score: 0.7,
      evidence: {
        min_distance_norm: 0.1,
        closing_speed_norm: 0.2,
        time_to_fall_sec: 0.3,
      },
    };

    expect(formatEventCause(cause)).toBe("외부 접촉 의심 · Track #42");
    expect(formatEventCause(null)).toBe("원인 후보 없음");
  });
});
