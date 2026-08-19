import { mockEvents } from "../mocks/mockEvents";
import { mockSummary } from "../mocks/mockSummary";
import { mockZoneStatus } from "../mocks/mockZoneStatus";
import type {
  CurrentRiskLevel,
  DashboardSummary,
  EventCause,
  EventType,
  SafetyEvent,
  Severity,
  ZoneStatus,
  ZoneType,
} from "../types/event";
import type { CurrentStatus, ZoneOccupancy } from "../types/status";
import { parseUtcTimestamp } from "../utils/eventDateTime";

export interface ApiResponse<T> {
  status: "success" | "error";
  data: T;
  message: string | null;
}

interface PaginatedResponse<T> {
  items?: T[];
}

export interface GetEventsParams {
  limit?: number;
  offset?: number;
  event_type?: string;
  zone_id?: string;
  created_from?: string;
  created_to?: string;
}

export interface EventListData {
  items: SafetyEvent[];
  total: number;
  limit: number;
  offset: number;
  count: number;
}

interface SummaryStats {
  total_events?: number;
  today_event_count?: number;
  recent_10min_event_count?: number;
  enter_count?: number;
  dwell_count?: number;
  exit_count?: number;
}

interface LoadedApiData<T> {
  data: T;
  errorMessage: string | null;
}

const EVENT_TYPES: readonly EventType[] = [
  "ENTER",
  "DWELL",
  "EXIT",
  "ENTER_RESTRICTED",
  "DANGER_ZONE_DWELL",
  "FALL_SUSPECT",
];
const SEVERITIES: readonly Severity[] = ["LOW", "MEDIUM", "HIGH"];
const STATUS_RISK_LEVELS: readonly CurrentRiskLevel[] = ["NORMAL", "HIGH"];
const ZONE_TYPES: readonly ZoneType[] = ["exit", "play", "restricted", "danger"];
const EVENT_CAUSE_TYPES = ["NEARBY_TRACK"] as const;
export const RECENT_EVENT_LIMIT = 5;

const API_BASE_URL = getEnvValue(
  import.meta.env.VITE_API_BASE_URL,
  "http://localhost:8000",
).replace(/\/+$/, "");
const API_MODE = getEnvValue(import.meta.env.VITE_API_MODE, "mock");

const emptySummary: DashboardSummary = {
  active_tracks: 0,
  today_event_count: null,
  danger_zone_occupancy: 0,
  recent_event_count: null,
};

const emptyCurrentStatus: CurrentStatus = {
  source: "unknown",
  frame_number: 0,
  active_track_count: 0,
  zone_occupancy: [],
  updated_at: null,
};

function getEnvValue(value: unknown, fallback: string) {
  return typeof value === "string" && value.trim().length > 0
    ? value.trim()
    : fallback;
}

function isApiMode() {
  return API_MODE.toLowerCase() === "api";
}

function createEmptySummary(): DashboardSummary {
  return { ...emptySummary };
}

function createEmptyCurrentStatus(): CurrentStatus {
  return { ...emptyCurrentStatus, zone_occupancy: [] };
}

function createMockCurrentStatus(): CurrentStatus {
  return {
    source: "mock",
    frame_number: 0,
    active_track_count: mockSummary.active_tracks,
    zone_occupancy: mockZoneStatus.map((zone) => ({
      zone_id: zone.zone_id,
      zone_name: zone.zone_name,
      current_count: zone.current_count,
      risk_level: zone.risk_level ?? "NORMAL",
    })),
    updated_at: null,
  };
}

function successResponse<T>(data: T): ApiResponse<T> {
  return {
    status: "success",
    data,
    message: null,
  };
}

function fallbackResponse<T>(data: T, message: string): ApiResponse<T> {
  return {
    status: "error",
    data,
    message,
  };
}

async function fetchApi<T>(
  path: string,
  options?: RequestInit,
): Promise<T | null> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    cache: "no-store",
  });

  if (!response.ok) {
    throw new Error(`API request failed: ${response.status}`);
  }

  let body: unknown;

  try {
    body = await response.json();
  } catch {
    throw new Error("API response was not valid JSON");
  }

  if (!isRecord(body)) {
    throw new Error("API response body was not an object");
  }

  if (body.status === "error") {
    throw new Error(readString(body.message, "API returned an error"));
  }

  if (body.status !== "success") {
    throw new Error("API response status was not success");
  }

  return (body.data ?? null) as T | null;
}

async function loadApiData<T>(
  path: string,
  normalize: (value: unknown) => T,
  fallback: T,
  options?: RequestInit,
): Promise<LoadedApiData<T>> {
  try {
    const data = await fetchApi<unknown>(path, options);
    return {
      data: normalize(data),
      errorMessage: null,
    };
  } catch (error) {
    return {
      data: fallback,
      errorMessage: errorToMessage(error),
    };
  }
}

function errorToMessage(error: unknown) {
  return error instanceof Error && error.message.length > 0
    ? error.message
    : "API request failed";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isPaginatedResponse<T>(value: unknown): value is PaginatedResponse<T> {
  return isRecord(value) && Array.isArray(value.items);
}

function isOneOf<T extends string>(
  values: readonly T[],
  value: unknown,
): value is T {
  return typeof value === "string" && values.includes(value as T);
}

function readOptionalNumber(value: unknown): number | undefined {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }

  if (typeof value === "string" && value.trim().length > 0) {
    const parsed = Number(value);

    if (Number.isFinite(parsed)) {
      return parsed;
    }
  }

  return undefined;
}

function readNumber(value: unknown, fallback = 0) {
  return readOptionalNumber(value) ?? fallback;
}

function readString(value: unknown, fallback = "") {
  return typeof value === "string" ? value : fallback;
}

function readOptionalString(value: unknown) {
  return typeof value === "string" ? value : undefined;
}

function readNullableString(value: unknown) {
  return typeof value === "string" ? value : null;
}

function normalizeEventType(value: unknown): EventType {
  if (isOneOf(EVENT_TYPES, value)) {
    return value;
  }

  // 알 수 없는(=아직 Frontend가 모르는) EventType을 ENTER로 조용히 바꾸지 않는다.
  // 값이 있는 문자열이면 그대로 통과시켜 화면에서 실제 값을 확인할 수 있게 하고,
  // 값 자체가 없을 때만 안전한 기본값으로 ENTER를 사용한다.
  return typeof value === "string" && value.trim().length > 0
    ? (value as EventType)
    : "ENTER";
}

function normalizeStatusRiskLevel(value: unknown): CurrentRiskLevel {
  return isOneOf(STATUS_RISK_LEVELS, value) ? value : "NORMAL";
}

function readOptionalSeverity(value: unknown) {
  return isOneOf(SEVERITIES, value) ? value : undefined;
}

function readOptionalZoneType(value: unknown) {
  return isOneOf(ZONE_TYPES, value) ? value : undefined;
}

function readOptionalEventConfidence(value: unknown): number | null {
  const parsed = readOptionalNumber(value);
  return parsed !== undefined && parsed >= 0 && parsed <= 1 ? parsed : null;
}

/** 필드가 하나라도 유효하지 않으면 cause 전체를 안전하게 null로 취급한다 (부분 cause 금지). */
function normalizeEventCause(value: unknown): EventCause | null {
  let causeValue = value;

  if (typeof causeValue === "string" && causeValue.trim().length > 0) {
    try {
      causeValue = JSON.parse(causeValue) as unknown;
    } catch {
      return null;
    }
  }

  if (!isRecord(causeValue)) {
    return null;
  }

  if (!isOneOf(EVENT_CAUSE_TYPES, causeValue.type)) {
    return null;
  }

  const trackId = readOptionalNumber(causeValue.track_id);
  const score = readOptionalNumber(causeValue.score);
  if (trackId === undefined || trackId < 0) {
    return null;
  }
  if (score === undefined || score < 0 || score > 1) {
    return null;
  }

  const evidenceValue = isRecord(causeValue.evidence) ? causeValue.evidence : {};
  const minDistanceNorm = readOptionalNumber(evidenceValue.min_distance_norm);
  const closingSpeedNorm = readOptionalNumber(evidenceValue.closing_speed_norm);
  const timeToFallSec = readOptionalNumber(evidenceValue.time_to_fall_sec);
  if (
    minDistanceNorm === undefined ||
    closingSpeedNorm === undefined ||
    timeToFallSec === undefined ||
    minDistanceNorm < 0 ||
    closingSpeedNorm < 0 ||
    timeToFallSec < 0
  ) {
    return null;
  }

  return {
    type: causeValue.type,
    track_id: trackId,
    score,
    evidence: {
      min_distance_norm: minDistanceNorm,
      closing_speed_norm: closingSpeedNorm,
      time_to_fall_sec: timeToFallSec,
    },
  };
}

function readTuple2(value: unknown): [number, number] {
  if (!Array.isArray(value)) {
    return [0, 0];
  }

  return [readNumber(value[0]), readNumber(value[1])];
}

function readTuple4(value: unknown): [number, number, number, number] {
  if (!Array.isArray(value)) {
    return [0, 0, 0, 0];
  }

  return [
    readNumber(value[0]),
    readNumber(value[1]),
    readNumber(value[2]),
    readNumber(value[3]),
  ];
}

function unwrapArray<T>(data: unknown): T[] {
  if (Array.isArray(data)) {
    return data as T[];
  }

  if (isPaginatedResponse<T>(data)) {
    return data.items as T[];
  }

  return [];
}

function normalizeSafetyEvent(value: unknown, index = 0): SafetyEvent {
  const event = isRecord(value) ? value : {};

  return {
    event_id: readString(event.event_id, `event_${index + 1}`),
    timestamp: readString(event.timestamp),
    event_type: normalizeEventType(event.event_type),
    track_id: readNumber(event.track_id),
    zone_id: readString(event.zone_id),
    created_at: readOptionalString(event.created_at),
    event_label: readOptionalString(event.event_label),
    severity: readOptionalSeverity(event.severity),
    zone_name: readOptionalString(event.zone_name),
    zone_type: readOptionalZoneType(event.zone_type),
    event_confidence: readOptionalEventConfidence(event.event_confidence),
    cause: normalizeEventCause(event.cause),
    bbox: readTuple4(event.bbox),
    foot_point: readTuple2(event.foot_point),
    frame_number: readNumber(event.frame_number),
    video_source: readString(event.video_source),
  };
}

function normalizeSafetyEvents(data: unknown): SafetyEvent[] {
  return unwrapArray<unknown>(data).map((event, index) =>
    normalizeSafetyEvent(event, index),
  );
}

function assertEventListData(data: unknown): void {
  if (Array.isArray(data) || isPaginatedResponse<unknown>(data)) {
    return;
  }

  throw new Error("Event list response format was invalid");
}

function normalizeSafetyEventsStrict(data: unknown): SafetyEvent[] {
  assertEventListData(data);
  return normalizeSafetyEvents(data);
}

function createEmptyEventListData(params?: GetEventsParams): EventListData {
  return {
    items: [],
    total: 0,
    limit: normalizeEventsLimit(params?.limit),
    offset: normalizeEventsOffset(params?.offset),
    count: 0,
  };
}

function normalizeEventsLimit(value: unknown) {
  const parsed = readOptionalNumber(value);
  return Math.min(500, Math.max(1, Math.floor(parsed ?? 50)));
}

function normalizeEventsOffset(value: unknown) {
  const parsed = readOptionalNumber(value);
  return Math.max(0, Math.floor(parsed ?? 0));
}

function normalizeEventListData(
  data: unknown,
  params?: GetEventsParams,
): EventListData {
  if (Array.isArray(data)) {
    const items = data.map((event, index) => normalizeSafetyEvent(event, index));

    return {
      items,
      total: items.length,
      limit: normalizeEventsLimit(params?.limit ?? (items.length || 50)),
      offset: normalizeEventsOffset(params?.offset),
      count: items.length,
    };
  }

  const eventList = isRecord(data) ? data : {};
  const items = unwrapArray<unknown>(eventList.items).map((event, index) =>
    normalizeSafetyEvent(event, index),
  );

  return {
    items,
    total: Math.max(0, Math.floor(readNumber(eventList.total, items.length))),
    limit: normalizeEventsLimit(eventList.limit ?? params?.limit),
    offset: normalizeEventsOffset(eventList.offset ?? params?.offset),
    count: Math.max(0, Math.floor(readNumber(eventList.count, items.length))),
  };
}

function normalizeEventListDataStrict(
  data: unknown,
  params?: GetEventsParams,
): EventListData {
  assertEventListData(data);
  return normalizeEventListData(data, params);
}

function normalizeSummaryStats(value: unknown): SummaryStats {
  const summary = isRecord(value) ? value : {};

  return {
    total_events: readOptionalNumber(summary.total_events),
    today_event_count: readOptionalNumber(summary.today_event_count),
    recent_10min_event_count: readOptionalNumber(
      summary.recent_10min_event_count,
    ),
    enter_count: readOptionalNumber(summary.enter_count),
    dwell_count: readOptionalNumber(summary.dwell_count),
    exit_count: readOptionalNumber(summary.exit_count),
  };
}

function normalizeSummaryStatsStrict(value: unknown): SummaryStats {
  if (!isRecord(value)) {
    throw new Error("Summary response format was invalid");
  }

  return normalizeSummaryStats(value);
}

function normalizeZoneOccupancy(value: unknown): ZoneOccupancy {
  const zone = isRecord(value) ? value : {};
  const zoneId = readString(zone.zone_id).trim();
  const zoneName = readString(zone.zone_name).trim();

  return {
    zone_id: zoneId,
    zone_name: zoneName || zoneId || "이름 없음",
    current_count: readNumber(zone.current_count),
    risk_level: normalizeStatusRiskLevel(zone.risk_level),
  };
}

function normalizeCurrentStatus(value: unknown): CurrentStatus {
  const status = isRecord(value) ? value : {};

  return {
    source: readString(status.source, emptyCurrentStatus.source),
    frame_number: readNumber(status.frame_number),
    active_track_count: readNumber(status.active_track_count),
    zone_occupancy: unwrapArray<unknown>(status.zone_occupancy).map(
      normalizeZoneOccupancy,
    ),
    updated_at: readNullableString(status.updated_at),
  };
}

function normalizeCurrentStatusStrict(value: unknown): CurrentStatus {
  if (!isRecord(value) || !Array.isArray(value.zone_occupancy)) {
    throw new Error("Current status response format was invalid");
  }

  return normalizeCurrentStatus(value);
}

function buildDashboardSummary(summary: SummaryStats): DashboardSummary {
  return {
    active_tracks: 0,
    today_event_count: summary.today_event_count ?? null,
    danger_zone_occupancy: 0,
    recent_event_count: summary.recent_10min_event_count ?? null,
  };
}

function buildEventsQuery(params: GetEventsParams = {}) {
  const searchParams = new URLSearchParams();

  if (params.limit !== undefined) {
    searchParams.set("limit", String(normalizeEventsLimit(params.limit)));
  }

  if (params.offset !== undefined) {
    searchParams.set("offset", String(normalizeEventsOffset(params.offset)));
  }

  if (params.event_type && params.event_type.trim().length > 0) {
    searchParams.set("event_type", params.event_type.trim());
  }

  if (params.zone_id && params.zone_id.trim().length > 0) {
    searchParams.set("zone_id", params.zone_id.trim());
  }

  if (params.created_from && params.created_from.trim().length > 0) {
    searchParams.set("created_from", params.created_from.trim());
  }

  if (params.created_to && params.created_to.trim().length > 0) {
    searchParams.set("created_to", params.created_to.trim());
  }

  const query = searchParams.toString();

  return query.length > 0 ? `?${query}` : "";
}

function getMockEventCreatedAtTime(event: SafetyEvent) {
  const createdAtDate = parseUtcTimestamp(event.created_at);

  return createdAtDate?.getTime() ?? null;
}

function getBoundaryTime(value: string | undefined) {
  if (value === undefined || value.trim().length === 0) {
    return null;
  }

  const parsed = new Date(value);

  return Number.isNaN(parsed.getTime()) ? null : parsed.getTime();
}

function filterMockEvents(params: GetEventsParams = {}) {
  const createdFrom = getBoundaryTime(params.created_from);
  const createdTo = getBoundaryTime(params.created_to);
  const eventType = params.event_type?.trim();
  const zoneId = params.zone_id?.trim();

  return mockEvents
    .filter((event) => {
      if (eventType && event.event_type !== eventType) {
        return false;
      }

      if (zoneId && event.zone_id !== zoneId) {
        return false;
      }

      const eventTime = getMockEventCreatedAtTime(event);

      if (createdFrom !== null && (eventTime === null || eventTime < createdFrom)) {
        return false;
      }

      if (createdTo !== null && (eventTime === null || eventTime >= createdTo)) {
        return false;
      }

      return true;
    })
    .sort((a, b) => {
      const bTime = getMockEventCreatedAtTime(b) ?? 0;
      const aTime = getMockEventCreatedAtTime(a) ?? 0;

      if (bTime !== aTime) {
        return bTime - aTime;
      }

      return b.event_id.localeCompare(a.event_id);
    });
}

function buildMockEventListData(params: GetEventsParams = {}): EventListData {
  const limit = normalizeEventsLimit(params.limit);
  const offset = normalizeEventsOffset(params.offset);
  const filteredEvents = filterMockEvents(params);
  const items = filteredEvents.slice(offset, offset + limit);

  return {
    items,
    total: filteredEvents.length,
    limit,
    offset,
    count: items.length,
  };
}

export function isEventsApiMode() {
  return isApiMode();
}

export async function getEvents(options?: {
  signal?: AbortSignal;
}): Promise<ApiResponse<SafetyEvent[]>> {
  if (!isApiMode()) {
    return successResponse(mockEvents);
  }

  const result = await loadApiData(
    "/events",
    normalizeSafetyEventsStrict,
    [],
    options,
  );

  if (result.errorMessage !== null) {
    return fallbackResponse(result.data, result.errorMessage);
  }

  return successResponse(result.data);
}

export async function getEventsPage(
  params: GetEventsParams = {},
  options?: { signal?: AbortSignal },
): Promise<ApiResponse<EventListData>> {
  if (!isApiMode()) {
    return successResponse(buildMockEventListData(params));
  }

  const fallback = createEmptyEventListData(params);
  const result = await loadApiData(
    `/events${buildEventsQuery(params)}`,
    (data) => normalizeEventListDataStrict(data, params),
    fallback,
    options,
  );

  if (result.errorMessage !== null) {
    return fallbackResponse(result.data, result.errorMessage);
  }

  return successResponse(result.data);
}

export async function getRecentEvents(
  limit = RECENT_EVENT_LIMIT,
  options?: { minutes?: number; signal?: AbortSignal },
): Promise<ApiResponse<SafetyEvent[]>> {
  const safeLimit = Math.max(
    1,
    Math.floor(readNumber(limit, RECENT_EVENT_LIMIT)),
  );
  if (!isApiMode()) {
    return successResponse(mockEvents.slice(0, safeLimit));
  }

  const searchParams = new URLSearchParams({ limit: String(safeLimit) });
  if (options?.minutes !== undefined) {
    const safeMinutes = Math.min(
      1440,
      Math.max(1, Math.floor(readNumber(options.minutes, 1))),
    );
    searchParams.set("minutes", String(safeMinutes));
  }

  const result = await loadApiData(
    `/events/recent?${searchParams.toString()}`,
    normalizeSafetyEventsStrict,
    [],
    { signal: options?.signal },
  );

  if (result.errorMessage !== null) {
    return fallbackResponse(result.data, result.errorMessage);
  }

  return successResponse(result.data);
}

export async function getCurrentStatus(options?: {
  signal?: AbortSignal;
}): Promise<ApiResponse<CurrentStatus>> {
  if (!isApiMode()) {
    return successResponse(createMockCurrentStatus());
  }

  const result = await loadApiData(
    "/status/current",
    normalizeCurrentStatusStrict,
    createEmptyCurrentStatus(),
    options,
  );

  if (result.errorMessage !== null) {
    return fallbackResponse(result.data, result.errorMessage);
  }

  return successResponse(result.data);
}

export async function getDashboardSummary(options?: {
  signal?: AbortSignal;
}): Promise<ApiResponse<DashboardSummary>> {
  if (!isApiMode()) {
    return successResponse(mockSummary);
  }

  const summaryResult = await loadApiData(
    "/summary",
    normalizeSummaryStatsStrict,
    {},
    options,
  );
  const dashboardSummary = buildDashboardSummary(summaryResult.data);

  if (summaryResult.errorMessage !== null) {
    return fallbackResponse(dashboardSummary, summaryResult.errorMessage);
  }

  return successResponse(dashboardSummary);
}

export async function getSummary(): Promise<ApiResponse<DashboardSummary>> {
  return getDashboardSummary();
}

export async function getZoneStatus(options?: {
  signal?: AbortSignal;
}): Promise<ApiResponse<ZoneStatus[]>> {
  if (!isApiMode()) {
    return successResponse(mockZoneStatus);
  }

  const response = await getCurrentStatus(options);
  const zones = response.data.zone_occupancy.map((zone) => ({
    zone_id: zone.zone_id,
    zone_name: zone.zone_name,
    current_count: zone.current_count,
    risk_level: zone.risk_level,
  }));

  return {
    status: response.status,
    data: zones,
    message: response.message,
  };
}
