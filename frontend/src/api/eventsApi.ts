import { mockEvents } from "../mocks/mockEvents";
import { mockSummary } from "../mocks/mockSummary";
import { mockZoneStatus } from "../mocks/mockZoneStatus";
import type {
  CurrentRiskLevel,
  DashboardSummary,
  EventType,
  SafetyEvent,
  Severity,
  ZoneStatus,
  ZoneType,
} from "../types/event";
import type { CurrentStatus, ZoneOccupancy } from "../types/status";

export interface ApiResponse<T> {
  status: "success" | "error";
  data: T;
  message: string | null;
}

interface PaginatedResponse<T> {
  items?: T[];
}

interface SummaryStats {
  total_events?: number;
  today_event_count?: number;
  enter_count?: number;
  dwell_count?: number;
  exit_count?: number;
}

interface LoadedApiData<T> {
  data: T;
  errorMessage: string | null;
}

const EVENT_TYPES: readonly EventType[] = ["ENTER", "DWELL", "EXIT"];
const SEVERITIES: readonly Severity[] = ["LOW", "MEDIUM", "HIGH"];
const STATUS_RISK_LEVELS: readonly CurrentRiskLevel[] = ["NORMAL", "HIGH"];
const ZONE_TYPES: readonly ZoneType[] = ["exit", "play", "restricted", "slide"];

const API_BASE_URL = getEnvValue(
  import.meta.env.VITE_API_BASE_URL,
  "http://localhost:8000",
).replace(/\/+$/, "");
const API_MODE = getEnvValue(import.meta.env.VITE_API_MODE, "mock");

const emptySummary: DashboardSummary = {
  active_tracks: 0,
  today_event_count: 0,
  danger_zone_occupancy: 0,
  recent_event_count: 0,
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

async function fetchApi<T>(path: string): Promise<T | null> {
  const response = await fetch(`${API_BASE_URL}${path}`);

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
): Promise<LoadedApiData<T>> {
  try {
    const data = await fetchApi<unknown>(path);
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
  return isOneOf(EVENT_TYPES, value) ? value : "ENTER";
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
    event_label: readOptionalString(event.event_label),
    severity: readOptionalSeverity(event.severity),
    zone_type: readOptionalZoneType(event.zone_type),
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

function normalizeSummaryStats(value: unknown): SummaryStats {
  const summary = isRecord(value) ? value : {};

  return {
    total_events: readOptionalNumber(summary.total_events),
    today_event_count: readOptionalNumber(summary.today_event_count),
    enter_count: readOptionalNumber(summary.enter_count),
    dwell_count: readOptionalNumber(summary.dwell_count),
    exit_count: readOptionalNumber(summary.exit_count),
  };
}

function normalizeZoneOccupancy(value: unknown): ZoneOccupancy {
  const zone = isRecord(value) ? value : {};

  return {
    zone_id: readString(zone.zone_id),
    zone_name: readString(zone.zone_name),
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

function countDangerZoneOccupancy(zoneOccupancy: ZoneOccupancy[]) {
  return zoneOccupancy
    .filter((zone) => zone.risk_level === "HIGH")
    .reduce((sum, zone) => sum + zone.current_count, 0);
}

function buildDashboardSummary(
  summary: SummaryStats,
  currentStatus: CurrentStatus,
  recentEvents: SafetyEvent[],
): DashboardSummary {
  return {
    active_tracks: currentStatus.active_track_count,
    today_event_count: summary.today_event_count ?? summary.total_events ?? 0,
    danger_zone_occupancy: countDangerZoneOccupancy(
      currentStatus.zone_occupancy,
    ),
    recent_event_count: recentEvents.length,
  };
}

function firstErrorMessage(...results: LoadedApiData<unknown>[]) {
  return (
    results.find((result) => result.errorMessage !== null)?.errorMessage ?? null
  );
}

export async function getEvents(): Promise<ApiResponse<SafetyEvent[]>> {
  if (!isApiMode()) {
    return successResponse(mockEvents);
  }

  const result = await loadApiData("/events", normalizeSafetyEvents, []);

  if (result.errorMessage !== null) {
    return fallbackResponse(result.data, result.errorMessage);
  }

  return successResponse(result.data);
}

export async function getRecentEvents(limit = 5): Promise<ApiResponse<SafetyEvent[]>> {
  if (!isApiMode()) {
    return successResponse(mockEvents.slice(0, limit));
  }

  const safeLimit = Math.max(1, Math.floor(readNumber(limit, 5)));
  const result = await loadApiData(
    `/events/recent?limit=${encodeURIComponent(String(safeLimit))}`,
    normalizeSafetyEvents,
    [],
  );

  if (result.errorMessage !== null) {
    return fallbackResponse(result.data, result.errorMessage);
  }

  return successResponse(result.data);
}

export async function getCurrentStatus(): Promise<ApiResponse<CurrentStatus>> {
  if (!isApiMode()) {
    return successResponse(createEmptyCurrentStatus());
  }

  const result = await loadApiData(
    "/status/current",
    normalizeCurrentStatus,
    createEmptyCurrentStatus(),
  );

  if (result.errorMessage !== null) {
    return fallbackResponse(result.data, result.errorMessage);
  }

  return successResponse(result.data);
}

export async function getDashboardSummary(): Promise<ApiResponse<DashboardSummary>> {
  if (!isApiMode()) {
    return successResponse(mockSummary);
  }

  const [summaryResult, statusResult, recentResult] = await Promise.all([
    loadApiData("/summary", normalizeSummaryStats, {}),
    loadApiData(
      "/status/current",
      normalizeCurrentStatus,
      createEmptyCurrentStatus(),
    ),
    loadApiData("/events/recent", normalizeSafetyEvents, []),
  ]);
  const dashboardSummary = buildDashboardSummary(
    summaryResult.data,
    statusResult.data,
    recentResult.data,
  );
  const errorMessage = firstErrorMessage(
    summaryResult,
    statusResult,
    recentResult,
  );

  if (errorMessage !== null) {
    return fallbackResponse(dashboardSummary, errorMessage);
  }

  return successResponse(dashboardSummary);
}

export async function getSummary(): Promise<ApiResponse<DashboardSummary>> {
  return getDashboardSummary();
}

export async function getZoneStatus(): Promise<ApiResponse<ZoneStatus[]>> {
  if (!isApiMode()) {
    return successResponse(mockZoneStatus);
  }

  const response = await getCurrentStatus();
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
