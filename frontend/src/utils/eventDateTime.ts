const SEOUL_TIME_ZONE = "Asia/Seoul";
const SQLITE_UTC_TIMESTAMP_PATTERN =
  /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:\.\d+)?$/;
const ISO_WITH_TIMEZONE_PATTERN = /(Z|[+-]\d{2}:?\d{2})$/i;

function isValidDate(date: Date) {
  return !Number.isNaN(date.getTime());
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

export function formatSeoulTime(date: Date) {
  return getSeoulDateParts(date).time;
}

export function getSeoulDateKey(date = new Date()) {
  return getSeoulDateParts(date).dateKey;
}
