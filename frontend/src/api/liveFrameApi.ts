export interface LiveFrameMetadata {
  source: string | null;
  frameNumber: string | null;
  capturedAt: string | null;
}

export type LiveFrameResult =
  | {
      status: "live";
      blob: Blob;
      metadata: LiveFrameMetadata;
    }
  | {
      status: "empty";
      metadata: LiveFrameMetadata;
    }
  | {
      status: "disabled";
      metadata: LiveFrameMetadata;
    };

const API_BASE_URL = getEnvValue(
  import.meta.env.VITE_API_BASE_URL,
  "http://localhost:8000",
).replace(/\/+$/, "");
const API_MODE = getEnvValue(import.meta.env.VITE_API_MODE, "mock");

function getEnvValue(value: unknown, fallback: string) {
  return typeof value === "string" && value.trim().length > 0
    ? value.trim()
    : fallback;
}

export function isLiveFrameApiMode() {
  return API_MODE.toLowerCase() === "api";
}

function readFrameMetadata(response?: Response): LiveFrameMetadata {
  return {
    source: response?.headers.get("X-Source") ?? null,
    frameNumber: response?.headers.get("X-Frame-Number") ?? null,
    capturedAt: response?.headers.get("X-Captured-At") ?? null,
  };
}

export async function getLiveFrame(options?: {
  signal?: AbortSignal;
}): Promise<LiveFrameResult> {
  if (!isLiveFrameApiMode()) {
    return {
      status: "disabled",
      metadata: readFrameMetadata(),
    };
  }

  const response = await fetch(`${API_BASE_URL}/live/frame`, {
    cache: "no-store",
    signal: options?.signal,
  });

  if (response.status === 204) {
    return {
      status: "empty",
      metadata: readFrameMetadata(response),
    };
  }

  if (!response.ok) {
    throw new Error(`Live frame request failed: ${response.status}`);
  }

  return {
    status: "live",
    blob: await response.blob(),
    metadata: readFrameMetadata(response),
  };
}
