import { act, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { PollingCallback, PollingOptions } from "./usePolling";
import { usePolling } from "./usePolling";

function PollingHarness({
  callback,
  enabled = true,
  intervalMs = 1000,
  options,
}: {
  callback: PollingCallback;
  enabled?: boolean;
  intervalMs?: number;
  options?: PollingOptions;
}) {
  usePolling(callback, intervalMs, enabled, options);
  return null;
}

function deferred() {
  let resolve!: () => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<void>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });

  return { promise, resolve, reject };
}

describe("usePolling", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("does not poll when disabled", () => {
    const callback = vi.fn();

    render(<PollingHarness callback={callback} enabled={false} />);

    expect(callback).not.toHaveBeenCalled();
  });

  it("runs immediately and schedules the next poll", async () => {
    const callback = vi.fn();

    render(<PollingHarness callback={callback} />);

    expect(callback).toHaveBeenCalledTimes(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });

    expect(callback).toHaveBeenCalledTimes(2);
  });

  it("does not start a duplicate request while an async poll is running", async () => {
    const pending = deferred();
    const callback = vi.fn().mockReturnValueOnce(pending.promise);

    render(<PollingHarness callback={callback} />);

    expect(callback).toHaveBeenCalledTimes(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });

    expect(callback).toHaveBeenCalledTimes(1);

    await act(async () => {
      pending.resolve();
      await pending.promise;
    });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });

    expect(callback).toHaveBeenCalledTimes(2);
  });

  it("aborts a never-settling request and schedules the next poll", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    let firstSignal: AbortSignal | null = null;
    const callback = vi.fn<PollingCallback>((context) => {
      if (callback.mock.calls.length === 1) {
        firstSignal = context.signal;
      }

      return new Promise<void>(() => {});
    });

    render(
      <PollingHarness
        callback={callback}
        intervalMs={100}
        options={{ requestTimeoutMs: 50 }}
      />,
    );

    expect(callback).toHaveBeenCalledTimes(1);
    expect(firstSignal?.aborted).toBe(false);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(50);
    });

    expect(firstSignal?.aborted).toBe(true);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(100);
    });

    expect(callback).toHaveBeenCalledTimes(2);
  });

  it("continues polling after a callback error", async () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
    const callback = vi
      .fn()
      .mockRejectedValueOnce(new Error("temporary failure"))
      .mockResolvedValue(undefined);

    render(<PollingHarness callback={callback} />);

    await act(async () => {
      await Promise.resolve();
    });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });

    expect(callback).toHaveBeenCalledTimes(2);
    expect(consoleError).toHaveBeenCalledWith(
      "Polling callback failed",
      expect.any(Error),
    );
  });

  it("throttles repeated polling failure logs", async () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
    const callback = vi
      .fn()
      .mockRejectedValue(new Error("temporary failure"));

    render(
      <PollingHarness
        callback={callback}
        intervalMs={100}
        options={{ errorLogCooldownMs: 1000 }}
      />,
    );

    await act(async () => {
      await Promise.resolve();
    });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(300);
    });

    expect(callback.mock.calls.length).toBeGreaterThanOrEqual(3);
    expect(consoleError).toHaveBeenCalledTimes(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(800);
    });

    expect(consoleError).toHaveBeenCalledTimes(2);
  });

  it("aborts the active poll and stops timers on unmount", () => {
    const pending = deferred();
    let signal: AbortSignal | null = null;
    const callback = vi.fn<PollingCallback>((context) => {
      signal = context.signal;
      return pending.promise;
    });

    const { unmount } = render(<PollingHarness callback={callback} />);

    expect(callback).toHaveBeenCalledTimes(1);
    expect(signal?.aborted).toBe(false);

    unmount();

    expect(signal?.aborted).toBe(true);

    act(() => {
      vi.advanceTimersByTime(5000);
    });

    expect(callback).toHaveBeenCalledTimes(1);
  });
});
