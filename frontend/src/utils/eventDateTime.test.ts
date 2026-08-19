import { describe, expect, it } from "vitest";
import {
  buildSeoulInclusiveDateRange,
  getSeoulDateParts,
  parseUtcTimestamp,
} from "./eventDateTime";

describe("eventDateTime", () => {
  it("builds Seoul inclusive date range with exclusive API end", () => {
    const result = buildSeoulInclusiveDateRange("2026-08-07", "2026-08-07");

    expect(result.errorMessage).toBeNull();
    expect(result.range).toMatchObject({
      createdFrom: "2026-08-07T00:00:00+09:00",
      createdTo: "2026-08-08T00:00:00+09:00",
      startDateKey: "2026-08-07",
      endDateKey: "2026-08-07",
      exclusiveEndDateKey: "2026-08-08",
      inclusiveDays: 1,
    });
  });

  it("does not shift SQLite UTC timestamps by browser local date parsing", () => {
    const parsed = parseUtcTimestamp("2026-08-06 15:00:00");

    expect(parsed).not.toBeNull();
    expect(getSeoulDateParts(parsed as Date).dateKey).toBe("2026-08-07");
  });

  it("rejects a start date after the end date", () => {
    const result = buildSeoulInclusiveDateRange("2026-08-08", "2026-08-07");

    expect(result.range).toBeNull();
    expect(result.errorMessage).toBe("시작일은 종료일보다 늦을 수 없습니다.");
  });

  it("rejects invalid date keys safely", () => {
    const result = buildSeoulInclusiveDateRange("2026-02-31", "2026-03-01");

    expect(result.range).toBeNull();
    expect(result.errorMessage).toBe("날짜 형식이 올바르지 않습니다.");
  });
});
