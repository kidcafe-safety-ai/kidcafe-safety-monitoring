import { useEffect, useRef } from "react";

export interface PollingContext {
  signal: AbortSignal;
  requestId: number;
  isActive: () => boolean;
}

export type PollingCallback = (
  context: PollingContext,
) => void | Promise<void>;

export interface PollingOptions {
  requestTimeoutMs?: number;
  errorLogCooldownMs?: number;
}

const DEFAULT_REQUEST_TIMEOUT_MS = 10000;
const DEFAULT_ERROR_LOG_COOLDOWN_MS = 5000;

export function usePolling(
  callback: PollingCallback,
  intervalMs: number,
  enabled = true,
  options: PollingOptions = {},
) {
  const callbackRef = useRef(callback);
  const requestTimeoutMs = Math.max(
    1,
    Math.floor(options.requestTimeoutMs ?? DEFAULT_REQUEST_TIMEOUT_MS),
  );
  const errorLogCooldownMs = Math.max(
    0,
    Math.floor(options.errorLogCooldownMs ?? DEFAULT_ERROR_LOG_COOLDOWN_MS),
  );

  useEffect(() => {
    callbackRef.current = callback;
  }, [callback]);

  useEffect(() => {
    if (!enabled) {
      return;
    }

    let active = true;
    let timerId: number | null = null;
    let watchdogTimerId: number | null = null;
    let requestId = 0;
    let controller: AbortController | null = null;
    let lastErrorLogAt = Number.NEGATIVE_INFINITY;

    function clearTimer() {
      if (timerId !== null) {
        window.clearTimeout(timerId);
        timerId = null;
      }
    }

    function clearWatchdogTimer() {
      if (watchdogTimerId !== null) {
        window.clearTimeout(watchdogTimerId);
        watchdogTimerId = null;
      }
    }

    function scheduleNext() {
      clearTimer();
      if (active) {
        timerId = window.setTimeout(run, intervalMs);
      }
    }

    function logPollingError(error: unknown) {
      const now = Date.now();

      if (now - lastErrorLogAt < errorLogCooldownMs) {
        return;
      }

      lastErrorLogAt = now;
      // Polling callback 오류가 다음 polling 예약을 막지 않도록 삼킨다.
      // 화면별 error state 처리는 callback 내부에서 수행한다.
      console.error("Polling callback failed", error);
    }

    async function run() {
      if (!active) {
        return;
      }

      const localController = new AbortController();
      controller = localController;
      requestId += 1;
      const currentRequestId = requestId;
      let requestActive = true;
      let didTimeout = false;

      const timeoutPromise = new Promise<never>((_, reject) => {
        watchdogTimerId = window.setTimeout(() => {
          didTimeout = true;
          requestActive = false;
          localController.abort();
          reject(
            new Error(`Polling callback timed out after ${requestTimeoutMs}ms`),
          );
        }, requestTimeoutMs);
      });

      try {
        await Promise.race([
          Promise.resolve(
            callbackRef.current({
              signal: localController.signal,
              requestId: currentRequestId,
              isActive: () =>
                active &&
                requestActive &&
                currentRequestId === requestId &&
                !localController.signal.aborted,
            }),
          ),
          timeoutPromise,
        ]);
      } catch (error) {
        if (active && (didTimeout || !localController.signal.aborted)) {
          logPollingError(error);
        }
      } finally {
        requestActive = false;
        clearWatchdogTimer();

        if (controller === localController) {
          controller = null;
        }

        if (active) {
          scheduleNext();
        }
      }
    }

    void run();

    return () => {
      active = false;
      clearTimer();
      clearWatchdogTimer();
      controller?.abort();
    };
  }, [intervalMs, enabled, requestTimeoutMs, errorLogCooldownMs]);
}
