import { useEffect, useRef, useState } from "react";
import {
  getLiveFrame,
  isLiveFrameApiMode,
  type LiveFrameMetadata,
} from "../api/liveFrameApi";

type LiveFrameStatus = "loading" | "live" | "empty" | "error";

const DEFAULT_POLL_INTERVAL_MS = 1000;
const REQUEST_TIMEOUT_MS = 3000;

const emptyMetadata: LiveFrameMetadata = {
  source: null,
  frameNumber: null,
  capturedAt: null,
};

interface LiveFrameViewProps {
  pollIntervalMs?: number;
}

function getStatusMessage(status: LiveFrameStatus) {
  if (status === "loading") {
    return "실시간 카메라 영상을 불러오는 중입니다.";
  }

  if (status === "error") {
    return "카메라 영상을 불러오지 못했습니다. 연결 상태를 확인해 주세요.";
  }

  return "카메라 연결을 기다리고 있습니다.";
}

function formatMetadataValue(value: string | null) {
  return value && value.trim().length > 0 ? value : "-";
}

export default function LiveFrameView({
  pollIntervalMs = DEFAULT_POLL_INTERVAL_MS,
}: LiveFrameViewProps) {
  const [status, setStatus] = useState<LiveFrameStatus>(
    isLiveFrameApiMode() ? "loading" : "empty",
  );
  const [frameUrl, setFrameUrl] = useState<string | null>(null);
  const [metadata, setMetadata] = useState<LiveFrameMetadata>(emptyMetadata);
  const objectUrlRef = useRef<string | null>(null);
  const controllerRef = useRef<AbortController | null>(null);
  const isRequestRunningRef = useRef(false);

  useEffect(() => {
    let isMounted = true;
    let intervalId: number | null = null;

    function revokeCurrentObjectUrl(resetFrameUrl = true) {
      if (objectUrlRef.current !== null) {
        URL.revokeObjectURL(objectUrlRef.current);
        objectUrlRef.current = null;
      }

      if (resetFrameUrl) {
        setFrameUrl(null);
      }
    }

    async function fetchFrame() {
      if (isRequestRunningRef.current) {
        return;
      }

      isRequestRunningRef.current = true;
      const controller = new AbortController();
      controllerRef.current = controller;
      const timeoutId = window.setTimeout(() => {
        controller.abort();
      }, REQUEST_TIMEOUT_MS);

      try {
        const result = await getLiveFrame({ signal: controller.signal });

        if (!isMounted) {
          return;
        }

        setMetadata(result.metadata);

        if (result.status === "live") {
          const nextUrl = URL.createObjectURL(result.blob);
          const previousUrl = objectUrlRef.current;
          objectUrlRef.current = nextUrl;
          setFrameUrl(nextUrl);
          setStatus("live");

          if (previousUrl !== null) {
            URL.revokeObjectURL(previousUrl);
          }
          return;
        }

        revokeCurrentObjectUrl();
        setStatus("empty");
      } catch {
        if (!isMounted) {
          return;
        }

        revokeCurrentObjectUrl();
        setMetadata(emptyMetadata);
        setStatus("error");
      } finally {
        window.clearTimeout(timeoutId);
        if (controllerRef.current === controller) {
          controllerRef.current = null;
        }
        isRequestRunningRef.current = false;
      }
    }

    if (!isLiveFrameApiMode()) {
      revokeCurrentObjectUrl();
      setMetadata(emptyMetadata);
      setStatus("empty");
      return () => {
        isMounted = false;
      };
    }

    fetchFrame();
    intervalId = window.setInterval(fetchFrame, pollIntervalMs);

    return () => {
      isMounted = false;

      if (intervalId !== null) {
        window.clearInterval(intervalId);
      }

      controllerRef.current?.abort();
      revokeCurrentObjectUrl(false);
    };
  }, [pollIntervalMs]);

  return (
    <div className={`video-placeholder live-frame-view live-frame-view--${status}`}>
      {status === "live" && frameUrl !== null ? (
        <>
          <img
            className="live-frame-image"
            src={frameUrl}
            alt="실시간 키즈카페 모니터링 화면"
          />
          <dl className="live-frame-meta" aria-label="실시간 영상 정보">
            <div>
              <dt>영상 소스</dt>
              <dd>{formatMetadataValue(metadata.source)}</dd>
            </div>
            <div>
              <dt>프레임 번호</dt>
              <dd>{formatMetadataValue(metadata.frameNumber)}</dd>
            </div>
            <div>
              <dt>수신 시각</dt>
              <dd>{formatMetadataValue(metadata.capturedAt)}</dd>
            </div>
          </dl>
        </>
      ) : (
        <div className="live-frame-state" role="status" aria-live="polite">
          <span>{getStatusMessage(status)}</span>
        </div>
      )}
    </div>
  );
}
