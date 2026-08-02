const SEOUL_TIME_ZONE = "Asia/Seoul";
const SQLITE_UTC_TIMESTAMP_PATTERN =
  /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:\.\d+)?$/;
const ISO_WITH_TIMEZONE_PATTERN = /(Z|[+-]\d{2}:?\d{2})$/i;
const DATE_KEY_PATTERN = /^(\d{4})-(\d{2})-(\d{2})$/;

function isValidDate(date: Date) {
  return !Number.isNaN(date.getTime());
}

function pad2(value: number) {
  return String(value).padStart(2, "0");
}

function parseDateKey(value: string) {
  const match = DATE_KEY_PATTERN.exec(value.trim());

  if (match === null) {
    return null;
  }

  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const utcDate = new Date(Date.UTC(year, month - 1, day));

  if (
    utcDate.getUTCFullYear() !== year ||
    utcDate.getUTCMonth() !== month - 1 ||
    utcDate.getUTCDate() !== day
  ) {
    return null;
  }

  return { year, month, day };
}

function addDaysToDateKey(dateKey: string, days: number) {
  const parsed = parseDateKey(dateKey);

  if (parsed === null) {
    return null;
  }

  const utcDate = new Date(
    Date.UTC(parsed.year, parsed.month - 1, parsed.day + days),
  );

  return `${utcDate.getUTCFullYear()}-${pad2(
    utcDate.getUTCMonth() + 1,
  )}-${pad2(utcDate.getUTCDate())}`;
}

function getDateKeyDiffDays(fromDateKey: string, toDateKey: string) {
  const from = parseDateKey(fromDateKey);
  const to = parseDateKey(toDateKey);

  if (from === null || to === null) {
    return null;
  }

  const fromTime = Date.UTC(from.year, from.month - 1, from.day);
  const toTime = Date.UTC(to.year, to.month - 1, to.day);

  return Math.floor((toTime - fromTime) / (1000 * 60 * 60 * 24));
}

function normalizeUtcTimestamp(value: string) {
  const trimmed = value.trim();

  if (SQLITE_UTC_TIMESTAMP_PATTERN.test(trimmed)) {
    return `${trimmed.replace(" ", "T")}Z`;
  }

  if (trimmed.includes("T") && !ISO_WITH_TIMEZONE_PATTERN.test(trimmed)) {
    return `${trimmed}Z`;
  }

  return trimmed;
}

export function parseUtcTimestamp(value: string | null | undefined) {
  if (typeof value !== "string" || value.trim().length === 0) {
    return null;
  }

  const parsedDate = new Date(normalizeUtcTimestamp(value));

  return isValidDate(parsedDate) ? parsedDate : null;
}

export function getSeoulDateParts(date: Date) {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: SEOUL_TIME_ZONE,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).formatToParts(date);
  const partMap = Object.fromEntries(parts.map((part) => [part.type, part.value]));

  return {
    dateKey: `${partMap.year}-${partMap.month}-${partMap.day}`,
    dateTime: `${partMap.year}-${partMap.month}-${partMap.day} ${partMap.hour}:${partMap.minute}:${partMap.second}`,
    time: `${partMap.hour}:${partMap.minute}:${partMap.second}`,
  };
}

export function formatSeoulDateTime(date: Date) {
  return getSeoulDateParts(date).dateTime;
}

export function formatSeoulDateTimeDisplay(date: Date) {
  const { dateKey, time } = getSeoulDateParts(date);
  const [year, month, day] = dateKey.split("-");

  return `${year}. ${month}. ${day}. ${time}`;
}

export function formatSeoulTime(date: Date) {
  return getSeoulDateParts(date).time;
}

export function getSeoulDateKey(date = new Date()) {
  return getSeoulDateParts(date).dateKey;
}

export interface SeoulInclusiveDateRange {
  createdFrom: string;
  createdTo: string;
  startDateKey: string;
  endDateKey: string;
  exclusiveEndDateKey: string;
  inclusiveDays: number;
}

export function buildSeoulInclusiveDateRange(
  startDateKey: string,
  endDateKey: string,
): { range: SeoulInclusiveDateRange | null; errorMessage: string | null } {
  const start = parseDateKey(startDateKey);
  const end = parseDateKey(endDateKey);

  if (start === null || end === null) {
    return {
      range: null,
      errorMessage: "날짜 형식이 올바르지 않습니다.",
    };
  }

  const diffDays = getDateKeyDiffDays(startDateKey, endDateKey);

  if (diffDays === null) {
    return {
      range: null,
      errorMessage: "날짜 범위를 계산할 수 없습니다.",
    };
  }

  if (diffDays < 0) {
    return {
      range: null,
      errorMessage: "시작일은 종료일보다 늦을 수 없습니다.",
    };
  }

  const exclusiveEndDateKey = addDaysToDateKey(endDateKey, 1);

  if (exclusiveEndDateKey === null) {
    return {
      range: null,
      errorMessage: "종료일 범위를 계산할 수 없습니다.",
    };
  }

  return {
    range: {
      createdFrom: `${startDateKey}T00:00:00+09:00`,
      createdTo: `${exclusiveEndDateKey}T00:00:00+09:00`,
      startDateKey,
      endDateKey,
      exclusiveEndDateKey,
      inclusiveDays: diffDays + 1,
    },
    errorMessage: null,
  };
}
