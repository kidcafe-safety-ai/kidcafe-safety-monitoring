import { mockZoneSettings } from "../mocks/mockZoneSettings";
import type { AlertZoneSetting } from "../types/zoneSettings";

interface MockApiResponse<T> {
  status: "success";
  data: T;
  message: string | null;
}

function successResponse<T>(data: T): MockApiResponse<T> {
  return {
    status: "success",
    data,
    message: null,
  };
}

// Development fixture only. Phase 4 replaces this path with the Zone Settings API.
export async function getMockZoneSettings(): Promise<
  MockApiResponse<AlertZoneSetting[]>
> {
  return successResponse(mockZoneSettings);
}
