import { useEffect, useRef } from "react";

export interface PollingContext {
  signal: AbortSignal;
  requestId: number;
  isActive: () => boolean;
}

export type PollingCallback = (
  context: PollingContext,
) => void | Promise<void>;

export function usePolling(
  callback: PollingCallback,
  intervalMs: number,
  enabled = true,
) {
  const callbackRef = useRef(callback);

  useEffect(() => {
    callbackRef.current = callback;
  }, [callback]);

  useEffect(() => {
    if (!enabled) {
      return;
    }

    let active = true;
    let timerId: number | null = null;
    let requestId = 0;
    let controller: AbortController | null = null;

    function clearTimer() {
      if (timerId !== null) {
        window.clearTimeout(timerId);
        timerId = null;
      }
    }

    function scheduleNext() {
      clearTimer();
      if (active) {
        timerId = window.setTimeout(run, intervalMs);
      }
    }

    async function run() {
      if (!active) {
        return;
      }

      controller = new AbortController();
      requestId += 1;
      const currentRequestId = requestId;

      try {
        await callbackRef.current({
          signal: controller.signal,
          requestId: currentRequestId,
          isActive: () => active && currentRequestId === requestId,
        });
      } catch (error) {
        if (!controller.signal.aborted) {
          // Polling callback 오류가 다음 polling 예약을 막지 않도록 삼킨다.
          // 화면별 error state 처리는 callback 내부에서 수행한다.
          console.error("Polling callback failed", error);
        }
      } finally {
        if (controller?.signal.aborted) {
          controller = null;
          return;
        }

        controller = null;
        scheduleNext();
      }
    }

    void run();

    return () => {
      active = false;
      clearTimer();
      controller?.abort();
    };
  }, [intervalMs, enabled]);
}
