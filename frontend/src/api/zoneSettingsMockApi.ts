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

// Phase 2 mock prototype only. This service is not connected to FastAPI.
export async function getMockZoneSettings(): Promise<
  MockApiResponse<AlertZoneSetting[]>
> {
  return successResponse(mockZoneSettings);
}
