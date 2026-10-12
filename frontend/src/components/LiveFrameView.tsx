import { useEffect, useState } from "react";
import { getLiveFrame, isLiveFrameApiMode } from "../api/liveFrameApi";

type LiveFrameStatus = "loading" | "live" | "empty" | "stale" | "error";

const DEFAULT_POLL_INTERVAL_MS = 1000;
const REQUEST_TIMEOUT_MS = 3000;

function configuredPollInterval() {
  const value = Number(import.meta.env.VITE_LIVE_FRAME_POLL_INTERVAL_MS);
  return Number.isFinite(value) && value >= 250 && value <= 60000
    ? Math.floor(value)
    : DEFAULT_POLL_INTERVAL_MS;
}

interface LiveFrameViewProps {
  pollIntervalMs?: number;
}

function getStatusMessage(status: LiveFrameStatus) {
  if (status === "loading") return "실시간 카메라 영상을 불러오는 중입니다.";
  if (status === "error") return "카메라 영상을 불러오지 못했습니다. 연결 상태를 확인해 주세요.";
  if (status === "stale") return "이전 영상이 만료되었습니다. 새 카메라 영상을 기다리고 있습니다.";
  return "카메라 연결을 기다리고 있습니다.";
}

export default function LiveFrameView({
  pollIntervalMs = configuredPollInterval(),
}: LiveFrameViewProps) {
  const [status, setStatus] = useState<LiveFrameStatus>(
    isLiveFrameApiMode() ? "loading" : "empty",
  );
  const [frameUrl, setFrameUrl] = useState<string | null>(null);

  useEffect(() => {
    if (!isLiveFrameApiMode()) return;

    let active = true;
    let hadFrame = false;
    let objectUrl: string | null = null;
    let timer: number | null = null;
    let controller: AbortController | null = null;
    const interval = Number.isFinite(pollIntervalMs) && pollIntervalMs >= 250
      ? pollIntervalMs : DEFAULT_POLL_INTERVAL_MS;

    function clearFrame() {
      if (objectUrl !== null) {
        URL.revokeObjectURL(objectUrl);
        objectUrl = null;
      }
      if (active) setFrameUrl(null);
    }

    async function poll() {
      if (!active) return;
      const requestController = new AbortController();
      controller = requestController;
      let timeout: number | null = null;
      const timeoutPromise = new Promise<never>((_, reject) => {
        timeout = window.setTimeout(() => {
          requestController.abort();
          reject(new Error("Live frame request timed out"));
        }, REQUEST_TIMEOUT_MS);
      });

      try {
        const result = await Promise.race([
          getLiveFrame({ signal: requestController.signal }),
          timeoutPromise,
        ]);
        if (!active) return;
        if (result.status === "live") {
          const nextUrl = URL.createObjectURL(result.blob);
          clearFrame();
          objectUrl = nextUrl;
          hadFrame = true;
          setFrameUrl(nextUrl);
          setStatus("live");
        } else {
          clearFrame();
          setStatus(hadFrame ? "stale" : "empty");
        }
      } catch {
        if (active) {
          clearFrame();
          setStatus("error");
        }
      } finally {
        if (timeout !== null) window.clearTimeout(timeout);
        if (controller === requestController) controller = null;
        if (active) timer = window.setTimeout(poll, interval);
      }
    }

    void poll();
    return () => {
      active = false;
      if (timer !== null) window.clearTimeout(timer);
      controller?.abort();
      clearFrame();
    };
  }, [pollIntervalMs]);

  return (
    <div className={`video-placeholder live-frame-view live-frame-view--${status}`}>
      {status === "live" && frameUrl !== null ? (
        <>
          <img className="live-frame-image" src={frameUrl} alt="실시간 키즈카페 모니터링 화면" />
          <span className="live-frame-connection-badge">연결됨</span>
        </>
      ) : (
        <div className="live-frame-state" role="status" aria-live="polite">
          <span>{getStatusMessage(status)}</span>
        </div>
      )}
    </div>
  );
}
