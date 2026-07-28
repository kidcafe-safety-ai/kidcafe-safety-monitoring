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

// Development fixture only. The contest flow must use the FastAPI-backed report path.
export async function getMockReports(): Promise<MockApiResponse<SafetyReport[]>> {
  return successResponse(mockReports);
}
