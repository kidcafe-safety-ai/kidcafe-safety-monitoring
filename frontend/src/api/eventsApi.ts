import { mockEvents } from "../mocks/mockEvents";
import { mockSummary } from "../mocks/mockSummary";
import { mockZoneStatus } from "../mocks/mockZoneStatus";
import type { DashboardSummary, SafetyEvent, ZoneStatus } from "../types/event";
import type { CurrentStatus } from "../types/status";

export interface ApiResponse<T> {
  status: "success" | "error";
  data: T;
  message: string | null;
}

interface PaginatedResponse<T> {
  items?: T[];
}

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";
const API_MODE = import.meta.env.VITE_API_MODE ?? "mock";

const emptySummary: DashboardSummary = {
  active_tracks: 0,
  today_event_count: 0,
  danger_zone_occupancy: 0,
  recent_event_count: 0,
};

const emptyCurrentStatus: CurrentStatus = {
  source: "camera_01",
  frame_number: 0,
  active_track_count: 0,
  zone_occupancy: [],
  updated_at: null,
};

function isApiMode() {
  return API_MODE === "api";
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

async function getJson<T>(path: string): Promise<ApiResponse<T>> {
  const response = await fetch(`${API_BASE_URL}${path}`);

  if (!response.ok) {
    throw new Error(`API request failed: ${response.status}`);
  }

  return response.json();
}

function unwrapArray<T>(data: T[] | PaginatedResponse<T> | null | undefined): T[] {
  if (Array.isArray(data)) {
    return data;
  }

  if (Array.isArray(data?.items)) {
    return data.items;
  }

  return [];
}

export async function getEvents(): Promise<ApiResponse<SafetyEvent[]>> {
  if (!isApiMode()) {
    return successResponse(mockEvents);
  }

  try {
    const body = await getJson<PaginatedResponse<SafetyEvent>>("/events");

    return {
      status: body.status,
      data: unwrapArray(body.data),
      message: body.message,
    };
  } catch {
    return fallbackResponse([], "이벤트 목록을 불러오지 못했습니다.");
  }
}

export async function getRecentEvents(limit = 5): Promise<ApiResponse<SafetyEvent[]>> {
  if (!isApiMode()) {
    return successResponse(mockEvents.slice(0, limit));
  }

  try {
    const body = await getJson<SafetyEvent[] | PaginatedResponse<SafetyEvent>>(
      `/events/recent?limit=${limit}`,
    );

    return {
      status: body.status,
      data: unwrapArray(body.data),
      message: body.message,
    };
  } catch {
    return fallbackResponse([], "최근 이벤트를 불러오지 못했습니다.");
  }
}

export async function getCurrentStatus(): Promise<ApiResponse<CurrentStatus>> {
  if (!isApiMode()) {
    return successResponse(emptyCurrentStatus);
  }

  try {
    const body = await getJson<CurrentStatus>("/status/current");

    return {
      status: body.status,
      data: {
        ...emptyCurrentStatus,
        ...(body.data ?? {}),
        zone_occupancy: Array.isArray(body.data?.zone_occupancy)
          ? body.data.zone_occupancy
          : [],
      },
      message: body.message,
    };
  } catch {
    return fallbackResponse(
      emptyCurrentStatus,
      "현재 상태 정보를 불러오지 못했습니다.",
    );
  }
}

export async function getDashboardSummary(): Promise<ApiResponse<DashboardSummary>> {
  if (!isApiMode()) {
    return successResponse(mockSummary);
  }

  try {
    const [summaryBody, statusBody, recentBody] = await Promise.all([
      getJson<Record<string, number>>("/summary"),
      getJson<CurrentStatus>("/status/current"),
      getJson<SafetyEvent[] | PaginatedResponse<SafetyEvent>>("/events/recent"),
    ]);

    const summary = summaryBody.data ?? {};
    const currentStatus = statusBody.data ?? emptyCurrentStatus;
    const recentEvents = unwrapArray(recentBody.data);
    const zoneOccupancy = Array.isArray(currentStatus.zone_occupancy)
      ? currentStatus.zone_occupancy
      : [];

    return successResponse({
      active_tracks: currentStatus.active_track_count ?? 0,
      today_event_count: summary.total_events ?? 0,
      danger_zone_occupancy: zoneOccupancy
        .filter(
          (zone) => zone.risk_level === "MEDIUM" || zone.risk_level === "HIGH",
        )
        .reduce((sum, zone) => sum + (zone.current_count ?? 0), 0),
      recent_event_count: recentEvents.length,
    });
  } catch {
    return fallbackResponse(
      emptySummary,
      "대시보드 요약 정보를 불러오지 못했습니다.",
    );
  }
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
