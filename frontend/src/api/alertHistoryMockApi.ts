import { mockAlertHistory } from "../mocks/mockAlertHistory";
import type { AlertHistoryItem } from "../types/alertHistory";

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
export async function getMockAlertHistory(): Promise<
  MockApiResponse<AlertHistoryItem[]>
> {
  return successResponse(mockAlertHistory);
}
