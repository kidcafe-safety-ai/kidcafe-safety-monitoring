import { mockSystemSettings } from "../mocks/mockSystemSettings";
import type { SystemSettingsMockData } from "../types/systemSettings";

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

// Final dashboard mock prototype only. This service is not connected to FastAPI.
export async function getMockSystemSettings(): Promise<
  MockApiResponse<SystemSettingsMockData>
> {
  return successResponse(mockSystemSettings);
}
