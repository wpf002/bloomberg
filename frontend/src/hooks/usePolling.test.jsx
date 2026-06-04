import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import usePolling from "./usePolling.js";

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.runOnlyPendingTimers();
  vi.useRealTimers();
});

describe("usePolling", () => {
  it("fetches once on mount and exposes the data", async () => {
    const fetcher = vi.fn().mockResolvedValue({ price: 42 });
    const { result } = renderHook(() => usePolling(fetcher, 0));
    expect(result.current.loading).toBe(true);
    await act(async () => {});
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(result.current.data).toEqual({ price: 42 });
    expect(result.current.loading).toBe(false);
    expect(result.current.error).toBeNull();
  });

  it("captures errors without throwing out of the effect", async () => {
    const boom = new Error("network down");
    const fetcher = vi.fn().mockRejectedValue(boom);
    const { result } = renderHook(() => usePolling(fetcher, 0));
    await act(async () => {});
    expect(result.current.error).toBe(boom);
    expect(result.current.data).toBeNull();
    expect(result.current.loading).toBe(false);
  });

  it("polls again after the interval elapses", async () => {
    const fetcher = vi.fn().mockResolvedValue({ n: 1 });
    renderHook(() => usePolling(fetcher, 1000));
    await act(async () => {});
    expect(fetcher).toHaveBeenCalledTimes(1);
    await act(async () => {
      vi.advanceTimersByTime(1000);
    });
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("does not set an interval when intervalMs <= 0", async () => {
    const fetcher = vi.fn().mockResolvedValue({});
    renderHook(() => usePolling(fetcher, 0));
    await act(async () => {});
    await act(async () => {
      vi.advanceTimersByTime(60000);
    });
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("refetch() triggers an immediate extra fetch and returns the result", async () => {
    const fetcher = vi.fn().mockResolvedValue({ v: "x" });
    const { result } = renderHook(() => usePolling(fetcher, 0));
    await act(async () => {});
    let returned;
    await act(async () => {
      returned = await result.current.refetch();
    });
    expect(returned).toEqual({ v: "x" });
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("stops fetching after unmount", async () => {
    const fetcher = vi.fn().mockResolvedValue({});
    const { unmount } = renderHook(() => usePolling(fetcher, 1000));
    await act(async () => {});
    unmount();
    await act(async () => {
      vi.advanceTimersByTime(5000);
    });
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
});
