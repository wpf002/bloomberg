import { useEffect, useRef, useState } from "react";
import { wsURL } from "../lib/api.js";

// Auto-reconnecting WebSocket subscription. Returns the latest message and
// connection status; messages are also passed to `onMessage` if provided so
// callers that need a *log* (alerts feed) can accumulate without waiting
// for the React state setter.
//
// The reconnect loop uses exponential backoff capped at 15s. We don't queue
// messages while disconnected — the topic is ephemeral by design (a price
// tick a minute old is uninteresting). Persistent state lives in REST.
export default function useStream(path, { onMessage, enabled = true } = {}) {
  const [status, setStatus] = useState(enabled ? "connecting" : "idle");
  const [last, setLast] = useState(null);
  const wsRef = useRef(null);
  const reopenTimerRef = useRef(null);
  const stoppedRef = useRef(false);
  const onMessageRef = useRef(onMessage);

  useEffect(() => {
    onMessageRef.current = onMessage;
  }, [onMessage]);

  useEffect(() => {
    if (!enabled || !path) {
      setStatus("idle");
      return;
    }
    stoppedRef.current = false;
    let backoff = 1000;

    const open = () => {
      if (stoppedRef.current) return;
      setStatus("connecting");
      const ws = new WebSocket(wsURL(path));
      wsRef.current = ws;
      ws.onopen = () => {
        setStatus("open");
        backoff = 1000;
      };
      ws.onmessage = (ev) => {
        try {
          const data = JSON.parse(ev.data);
          if (data?.type === "ping") {
            // Reply with a pong so the server's liveness watchdog stays
            // satisfied. Railway's WS proxy idles silent connections at
            // 90s, so the server pings every 30s and expects a pong
            // within 10s — see backend/api/routes/streams.py.
            try {
              ws.send(JSON.stringify({ type: "pong" }));
            } catch {
              // socket already closing; harmless
            }
            return;
          }
          setLast(data);
          onMessageRef.current?.(data);
        } catch {
          // ignore non-JSON frames
        }
      };
      ws.onerror = () => {
        setStatus("error");
      };
      ws.onclose = () => {
        if (stoppedRef.current) return;
        setStatus("reconnecting");
        reopenTimerRef.current = setTimeout(open, backoff);
        backoff = Math.min(backoff * 2, 15_000);
      };
    };

    open();

    return () => {
      stoppedRef.current = true;
      if (reopenTimerRef.current) clearTimeout(reopenTimerRef.current);
      if (wsRef.current) wsRef.current.close();
      wsRef.current = null;
    };
  }, [path, enabled]);

  return { status, last };
}
