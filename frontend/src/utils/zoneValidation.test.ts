import { describe, expect, it } from "vitest";
import type { Zone } from "../types/zoneSettings";
import { validateZones } from "./zoneValidation";

function zone(overrides: Partial<Zone> = {}): Zone {
  return {
    zone_id: "zone-a",
    zone_name: "놀이구역 A",
    type: "polygon",
    zone_type: "play",
    points: [
      [0.1, 0.1],
      [0.3, 0.1],
      [0.3, 0.3],
      [0.1, 0.3],
    ],
    rules: {
      enter_alert: true,
      dwell_threshold_sec: 5,
    },
    ...overrides,
  };
}

describe("zoneValidation", () => {
  it("accepts a valid polygon zone", () => {
    expect(validateZones([zone()])).toEqual([]);
  });

  it("rejects invalid polygon coordinates and self intersections", () => {
    const issues = validateZones([
      zone({
        points: [
          [0.1, 0.1],
          [0.9, 0.9],
          [0.1, 0.9],
          [0.9, 0.1],
        ],
      }),
      zone({
        zone_id: "zone-b",
        points: [
          [0.1, 0.1],
          [0.1, 0.1],
          [1.2, 0.2],
        ],
      }),
    ]);

    expect(issues.map((issue) => issue.message)).toEqual(
      expect.arrayContaining([
        "self-intersection polygon은 저장할 수 없습니다.",
        "중복 좌표가 포함되어 있습니다.",
        "좌표 x, y는 0.0 이상 1.0 이하여야 합니다.",
      ]),
    );
  });

  it("rejects duplicate zone_id and missing required fields", () => {
    const issues = validateZones([
      zone({ zone_id: "dup" }),
      zone({ zone_id: "dup", zone_name: "" }),
    ]);

    expect(issues.map((issue) => issue.message)).toEqual(
      expect.arrayContaining([
        "zone_id가 중복되었습니다.",
        "zone_name은 비워둘 수 없습니다.",
      ]),
    );
  });

  it("rejects unsupported zone_type and invalid dwell threshold", () => {
    const issues = validateZones([
      zone({
        zone_type: "unknown" as Zone["zone_type"],
        rules: {
          enter_alert: true,
          dwell_threshold_sec: 3601,
        },
      }),
    ]);

    expect(issues.map((issue) => issue.message)).toEqual(
      expect.arrayContaining([
        "지원하지 않는 zone_type입니다.",
        "dwell_threshold_sec는 0 이상 3600 이하 정수여야 합니다.",
      ]),
    );
  });

  it("returns validation issues that can block save requests", () => {
    const issues = validateZones([zone({ zone_id: "" })]);

    expect(issues.length).toBeGreaterThan(0);
    expect(issues[0]).toMatchObject({
      field: "zone_id",
      message: "zone_id는 비워둘 수 없습니다.",
    });
  });
});
