import { mockEvents } from "../mocks/mockEvents";
import { mockSummary } from "../mocks/mockSummary";
import { mockZoneStatus } from "../mocks/mockZoneStatus";
import type { DashboardSummary, SafetyEvent, ZoneStatus } from "../types/event";

export interface ApiResponse<T> {
  status: "success";
  data: T;
  message: string | null;
}

function successResponse<T>(data: T): ApiResponse<T> {
  return {
    status: "success",
    data,
    message: null,
  };
}

export async function getEvents(): Promise<ApiResponse<SafetyEvent[]>> {
  return successResponse(mockEvents);
}

export async function getRecentEvents(limit = 5): Promise<ApiResponse<SafetyEvent[]>> {
  return successResponse(mockEvents.slice(0, limit));
}

export async function getSummary(): Promise<ApiResponse<DashboardSummary>> {
  return successResponse(mockSummary);
}

export async function getZoneStatus(): Promise<ApiResponse<ZoneStatus[]>> {
  return successResponse(mockZoneStatus);
}
