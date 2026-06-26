import { mockReports } from "../mocks/mockReports";
import type { SafetyReport } from "../types/report";

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

// Phase 2.5 mock prototype only. This service is not connected to FastAPI.
export async function getMockReports(): Promise<MockApiResponse<SafetyReport[]>> {
  return successResponse(mockReports);
}
