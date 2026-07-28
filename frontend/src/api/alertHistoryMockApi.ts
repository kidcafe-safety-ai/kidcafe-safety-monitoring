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

// Legacy development fixture. AlertHistory API mode uses eventsApi instead.
export async function getMockAlertHistory(): Promise<
  MockApiResponse<AlertHistoryItem[]>
> {
  return successResponse(mockAlertHistory);
}
