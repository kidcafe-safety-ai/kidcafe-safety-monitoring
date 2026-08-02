import { mockZoneConfig } from "../mocks/mockZoneSettings";
import type {
  PutZonesRequest,
  Zone,
  ZoneApiErrorType,
  ZoneApiResponse,
  ZoneConfig,
  ZonePoint,
  ZoneRules,
  ZoneType,
} from "../types/zoneSettings";

const ZONE_TYPES: readonly ZoneType[] = ["play", "exit", "restricted", "danger"];
const API_BASE_URL = getEnvValue(
  import.meta.env.VITE_API_BASE_URL,
  "http://localhost:8000",
).replace(/\/+$/, "");
const API_MODE = getEnvValue(import.meta.env.VITE_API_MODE, "mock");

let mockConfig = cloneZoneConfig(mockZoneConfig);
let mockVersionCounter = 1;

function getEnvValue(value: unknown, fallback: string) {
  return typeof value === "string" && value.trim().length > 0
    ? value.trim()
    : fallback;
}

function isApiMode() {
  return API_MODE.toLowerCase() === "api";
}

function cloneZoneConfig(config: ZoneConfig): ZoneConfig {
  return {
    ...config,
    zones: config.zones.map(cloneZone),
  };
}

function cloneZone(zone: Zone): Zone {
  return {
    ...zone,
    points: zone.points.map(([x, y]) => [x, y]),
    rules: { ...zone.rules },
  };
}

function successResponse<T>(data: T): ZoneApiResponse<T> {
  return {
    status: "success",
    data,
    message: null,
  };
}

function errorResponse<T>(
  errorType: ZoneApiErrorType,
  message: string,
  options?: { statusCode?: number; details?: string[] },
): ZoneApiResponse<T> {
  return {
    status: "error",
    data: null,
    message,
    error_type: errorType,
    status_code: options?.statusCode,
    details: options?.details,
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isOneOf<T extends string>(
  values: readonly T[],
  value: unknown,
): value is T {
  return typeof value === "string" && values.includes(value as T);
}

function readString(value: unknown) {
  return typeof value === "string" ? value : "";
}

function readBoolean(value: unknown) {
  return typeof value === "boolean" ? value : false;
}

function readNumber(value: unknown) {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

function normalizePoint(value: unknown): ZonePoint {
  if (!Array.isArray(value)) {
    return [0, 0];
  }

  return [readNumber(value[0]), readNumber(value[1])];
}

function normalizeRules(value: unknown): ZoneRules {
  const rules = isRecord(value) ? value : {};

  return {
    enter_alert: readBoolean(rules.enter_alert),
    dwell_threshold_sec: Math.trunc(readNumber(rules.dwell_threshold_sec)),
  };
}

function normalizeZone(value: unknown): Zone {
  const zone = isRecord(value) ? value : {};
  const zoneType = isOneOf(ZONE_TYPES, zone.zone_type) ? zone.zone_type : "play";

  return {
    zone_id: readString(zone.zone_id),
    zone_name: readString(zone.zone_name),
    type: "polygon",
    zone_type: zoneType,
    points: Array.isArray(zone.points) ? zone.points.map(normalizePoint) : [],
    rules: normalizeRules(zone.rules),
  };
}

function normalizeZoneConfig(value: unknown): ZoneConfig | null {
  if (!isRecord(value) || !Array.isArray(value.zones)) {
    return null;
  }

  const version = readString(value.version);
  const updatedAt = readString(value.updated_at);

  if (version.length === 0 || updatedAt.length === 0) {
    return null;
  }

  return {
    version,
    updated_at: updatedAt,
    zones: value.zones.map(normalizeZone),
  };
}

function safeMessage(value: unknown, fallback: string) {
  const message = readString(value).trim();

  if (message.length === 0) {
    return fallback;
  }

  if (message.includes("\\") || message.includes("/") || message.length > 180) {
    return fallback;
  }

  return message;
}

function collectDetails(value: unknown) {
  if (!isRecord(value)) {
    return undefined;
  }

  const detail = value.detail;

  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        if (typeof item === "string") {
          return item;
        }

        if (isRecord(item) && typeof item.msg === "string") {
          return item.msg;
        }

        return null;
      })
      .filter((item): item is string => item !== null)
      .slice(0, 5);
  }

  if (typeof detail === "string") {
    return [detail];
  }

  return undefined;
}

function errorTypeFromStatus(statusCode: number): ZoneApiErrorType {
  if (statusCode === 409) {
    return "conflict";
  }

  if (statusCode === 422) {
    return "validation";
  }

  if (statusCode >= 500) {
    return "server";
  }

  return "unknown";
}

function defaultErrorMessage(errorType: ZoneApiErrorType) {
  if (errorType === "conflict") {
    return "다른 사용자가 Zone 설정을 먼저 변경했습니다.";
  }

  if (errorType === "validation") {
    return "Zone 설정 validation에 실패했습니다.";
  }

  if (errorType === "network") {
    return "API 연결에 실패했습니다.";
  }

  if (errorType === "schema") {
    return "Zone 설정 응답 형식이 올바르지 않습니다.";
  }

  if (errorType === "server") {
    return "Zone 설정을 처리할 수 없습니다.";
  }

  return "Zone 설정 요청에 실패했습니다.";
}

async function readResponseBody(response: Response) {
  try {
    return (await response.json()) as unknown;
  } catch {
    return null;
  }
}

async function requestZones<T>(
  path: string,
  options: RequestInit,
  normalize: (value: unknown) => T | null,
): Promise<ZoneApiResponse<T>> {
  let response: Response;

  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...(options.headers ?? {}),
      },
      cache: "no-store",
    });
  } catch {
    return errorResponse<T>("network", defaultErrorMessage("network"));
  }

  const body = await readResponseBody(response);
  const envelope = isRecord(body) ? body : {};
  const responseStatus = envelope.status;

  if (!response.ok || responseStatus === "error") {
    const errorType = errorTypeFromStatus(response.status);
    return errorResponse<T>(
      errorType,
      safeMessage(envelope.message, defaultErrorMessage(errorType)),
      {
        statusCode: response.status,
        details: collectDetails(envelope),
      },
    );
  }

  if (responseStatus !== "success") {
    return errorResponse<T>("schema", defaultErrorMessage("schema"), {
      statusCode: response.status,
    });
  }

  const data = normalize(envelope.data);

  if (data === null) {
    return errorResponse<T>("schema", defaultErrorMessage("schema"), {
      statusCode: response.status,
    });
  }

  return successResponse(data);
}

function createMockVersion() {
  const suffix = String(mockVersionCounter).padStart(64, "b").slice(-64);
  mockVersionCounter += 1;

  return `sha256:${suffix}`;
}

export async function getZones(): Promise<ZoneApiResponse<ZoneConfig>> {
  if (!isApiMode()) {
    return successResponse(cloneZoneConfig(mockConfig));
  }

  return requestZones<ZoneConfig>(
    "/zones",
    { method: "GET" },
    normalizeZoneConfig,
  );
}

export async function putZones(
  request: PutZonesRequest,
): Promise<ZoneApiResponse<ZoneConfig>> {
  if (!isApiMode()) {
    if (request.expected_version !== mockConfig.version) {
      return errorResponse<ZoneConfig>(
        "conflict",
        defaultErrorMessage("conflict"),
        { statusCode: 409 },
      );
    }

    mockConfig = {
      version: createMockVersion(),
      updated_at: new Date().toISOString(),
      zones: request.zones.map(cloneZone),
    };

    return successResponse(cloneZoneConfig(mockConfig));
  }

  return requestZones<ZoneConfig>(
    "/zones",
    {
      method: "PUT",
      body: JSON.stringify(request),
    },
    normalizeZoneConfig,
  );
}
