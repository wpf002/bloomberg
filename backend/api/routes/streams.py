"""WebSocket fan-out endpoints.

Three topics: quotes, news, alerts. Quotes accept a `?symbols=AAPL,MSFT`
filter — when present, the route subscribes only to symbol-scoped topics
on the hub *and* registers those symbols upstream with the AlpacaStreamer
(so we only burn an upstream subscription when somebody is listening).

Keepalive (Railway-aware):
  - Server emits a `{"type":"ping","ts":...}` JSON frame every 30s. The
    Railway proxy idles inactive WS connections at 90s, so 30s gives us
    three ticks per idle window — comfortable margin.
  - Server reads frames from the client; a `{"type":"pong"}` resets the
    pong-watchdog. If 10s pass after a ping with no pong (or any message,
    which we treat as proof of a live socket), we close cleanly with
    code 1011 ("internal error / liveness").
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Iterable

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from ...core.auth import user_from_token
from ...core.config import settings
from ...core.streaming import hub, streamer

logger = logging.getLogger(__name__)
router = APIRouter()

HEARTBEAT_SECONDS = 30.0
PONG_TIMEOUT_SECONDS = 10.0


async def _pump(ws: WebSocket, queues: list[asyncio.Queue]) -> None:
    """Multiplex N hub queues onto one WebSocket with ping/pong keepalive.

    Three concurrent task families share one `asyncio.wait` loop:
      - one `q.get()` per subscribed hub queue (data fan-in)
      - one timer scheduling the next ping
      - one `ws.receive_text()` so we can observe pong frames (and any
        client-initiated frame, which counts as proof of liveness)
    Whenever the client sends *anything*, we update `last_client_msg`.
    A ping that goes >10s without any client traffic afterwards trips
    the pong watchdog and we close the socket.
    """
    pending: set[asyncio.Task] = set()
    last_client_msg = time.monotonic()
    awaiting_pong = False

    def schedule_get(q: asyncio.Queue) -> asyncio.Task:
        task = asyncio.create_task(q.get())
        task._kind = "queue"  # type: ignore[attr-defined]
        task._origin_queue = q  # type: ignore[attr-defined]
        return task

    def schedule_recv() -> asyncio.Task:
        task = asyncio.create_task(ws.receive_text())
        task._kind = "recv"  # type: ignore[attr-defined]
        return task

    def schedule_ping() -> asyncio.Task:
        task = asyncio.create_task(asyncio.sleep(HEARTBEAT_SECONDS))
        task._kind = "ping"  # type: ignore[attr-defined]
        return task

    for q in queues:
        pending.add(schedule_get(q))
    pending.add(schedule_ping())
    pending.add(schedule_recv())

    try:
        while True:
            done, pending = await asyncio.wait(
                pending,
                timeout=PONG_TIMEOUT_SECONDS,
                return_when=asyncio.FIRST_COMPLETED,
            )

            # Liveness: if we asked for a pong > PONG_TIMEOUT_SECONDS ago
            # and nothing has come back from the client (no pong, no other
            # frame), close. This catches Railway / corp-proxy half-open
            # sockets where send still works but the peer is gone.
            if awaiting_pong and (time.monotonic() - last_client_msg) > PONG_TIMEOUT_SECONDS:
                logger.debug("ws closing: no pong within %.1fs", PONG_TIMEOUT_SECONDS)
                try:
                    await ws.close(code=1011)
                finally:
                    return

            for task in done:
                kind = getattr(task, "_kind", None)
                if kind == "ping":
                    try:
                        await ws.send_text(json.dumps({"type": "ping", "ts": int(time.time())}))
                    except Exception:
                        return
                    awaiting_pong = True
                    pending.add(schedule_ping())
                    continue
                if kind == "recv":
                    # An exception (disconnect) propagates the WebSocketDisconnect
                    # up to the route handler.
                    raw = task.result()
                    last_client_msg = time.monotonic()
                    awaiting_pong = False
                    # We don't actually need the message body — the fact
                    # that the client could send proves liveness. Still,
                    # skip our own ping echoes if the client mirrors them.
                    try:
                        parsed = json.loads(raw)
                        if isinstance(parsed, dict) and parsed.get("type") == "pong":
                            pass
                    except Exception:
                        pass
                    pending.add(schedule_recv())
                    continue
                # queue task: fan-out a real message
                msg = task.result()
                try:
                    await ws.send_text(json.dumps(msg, default=str))
                except Exception:
                    return
                origin = task._origin_queue  # type: ignore[attr-defined]
                pending.add(schedule_get(origin))
    finally:
        for task in pending:
            task.cancel()


def _parse_symbols(symbols: str | None) -> list[str]:
    if not symbols:
        return []
    return [s.strip().upper() for s in symbols.split(",") if s.strip()]


@router.websocket("/quotes")
async def ws_quotes(ws: WebSocket, symbols: str | None = Query(None)) -> None:
    parsed = _parse_symbols(symbols)
    await ws.accept()
    queues: list[asyncio.Queue] = []
    try:
        if parsed:
            await streamer.add_symbols(parsed)
            for sym in parsed:
                queues.append(await hub.subscribe(f"quotes:{sym}"))
        else:
            queues.append(await hub.subscribe("quotes"))
        await ws.send_text(json.dumps({"type": "ready", "symbols": parsed}))
        await _pump(ws, queues)
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.debug("quotes ws closed: %s", exc)
    finally:
        for q in queues:
            # We don't know the topic from the queue object, so iterate the
            # known topics and drop the queue from each — cheap, idempotent.
            for topic in (("quotes", *(f"quotes:{s}" for s in parsed))):
                await hub.unsubscribe(topic, q)
        if parsed:
            await streamer.remove_symbols(parsed)


@router.websocket("/news")
async def ws_news(ws: WebSocket) -> None:
    await ws.accept()
    queue = await hub.subscribe("news")
    try:
        await ws.send_text(json.dumps({"type": "ready"}))
        await _pump(ws, [queue])
    except WebSocketDisconnect:
        pass
    finally:
        await hub.unsubscribe("news", queue)


@router.websocket("/alerts")
async def ws_alerts(ws: WebSocket) -> None:
    """Per-user alert stream when authenticated, global when not.

    The session cookie rides along with the WS upgrade handshake; we read it
    via `ws.cookies` and decode the JWT in pure Python — no DB hit required
    on the WS hot path. Logged-in users subscribe to `alerts:user:{id}` and
    therefore only see fires for their own rules.
    """
    await ws.accept()
    cookie = ws.cookies.get(settings.session_cookie_name)
    user_id = user_from_token(cookie)
    topic = f"alerts:user:{user_id}" if user_id else "alerts"
    queue = await hub.subscribe(topic)
    try:
        await ws.send_text(json.dumps({"type": "ready", "scope": "user" if user_id else "global"}))
        await _pump(ws, [queue])
    except WebSocketDisconnect:
        pass
    finally:
        await hub.unsubscribe(topic, queue)
