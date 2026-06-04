import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import useStream from "./useStream.js";

// Minimal controllable WebSocket double. Tests drive lifecycle by hand.
class FakeWebSocket {
  static instances = [];
  constructor(url) {
    this.url = url;
    this.sent = [];
    this.onopen = null;
    this.onmessage = null;
    this.onerror = null;
    this.onclose = null;
    this.readyState = 0;
    FakeWebSocket.instances.push(this);
  }
  send(data) {
    this.sent.push(data);
  }
  close() {
    this.readyState = 3;
    this.onclose?.({});
  }
  // helpers
  _open() {
    this.readyState = 1;
    this.onopen?.({});
  }
  _emit(obj) {
    this.onmessage?.({ data: typeof obj === "string" ? obj : JSON.stringify(obj) });
  }
}

beforeEach(() => {
  FakeWebSocket.instances = [];
  vi.stubGlobal("WebSocket", FakeWebSocket);
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("useStream", () => {
  it("stays idle when disabled and opens no socket", () => {
    const { result } = renderHook(() => useStream("/api/ws/quotes", { enabled: false }));
    expect(result.current.status).toBe("idle");
    expect(FakeWebSocket.instances).toHaveLength(0);
  });

  it("connects and reports open on socket open", async () => {
    const { result } = renderHook(() => useStream("/api/ws/quotes"));
    expect(result.current.status).toBe("connecting");
    expect(FakeWebSocket.instances).toHaveLength(1);
    act(() => FakeWebSocket.instances[0]._open());
    expect(result.current.status).toBe("open");
  });

  it("surfaces the latest parsed message", () => {
    const { result } = renderHook(() => useStream("/api/ws/quotes"));
    act(() => FakeWebSocket.instances[0]._open());
    act(() => FakeWebSocket.instances[0]._emit({ symbol: "AAPL", price: 1 }));
    expect(result.current.last).toEqual({ symbol: "AAPL", price: 1 });
  });

  it("invokes onMessage for data frames but not for pings", () => {
    const onMessage = vi.fn();
    renderHook(() => useStream("/api/ws/quotes", { onMessage }));
    const ws = FakeWebSocket.instances[0];
    act(() => ws._open());
    act(() => ws._emit({ type: "ping" }));
    expect(onMessage).not.toHaveBeenCalled();
    // a ping is answered with a pong
    expect(ws.sent).toContain(JSON.stringify({ type: "pong" }));
    act(() => ws._emit({ hello: "world" }));
    expect(onMessage).toHaveBeenCalledWith({ hello: "world" });
  });

  it("ignores malformed (non-JSON) frames", () => {
    const { result } = renderHook(() => useStream("/api/ws/quotes"));
    const ws = FakeWebSocket.instances[0];
    act(() => ws._open());
    act(() => ws._emit("not json{"));
    expect(result.current.last).toBeNull();
  });

  it("reconnects with backoff after an unexpected close", () => {
    const { result } = renderHook(() => useStream("/api/ws/quotes"));
    const ws = FakeWebSocket.instances[0];
    act(() => ws._open());
    act(() => ws.onclose?.({}));
    expect(result.current.status).toBe("reconnecting");
    // first backoff is 1000ms — advancing opens a new socket
    act(() => vi.advanceTimersByTime(1000));
    expect(FakeWebSocket.instances).toHaveLength(2);
  });

  it("does not reconnect after unmount", () => {
    const { unmount } = renderHook(() => useStream("/api/ws/quotes"));
    act(() => FakeWebSocket.instances[0]._open());
    unmount();
    act(() => vi.advanceTimersByTime(30000));
    expect(FakeWebSocket.instances).toHaveLength(1);
  });
});
