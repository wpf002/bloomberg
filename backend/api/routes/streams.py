"""WebSocket fan-out endpoints.

Three topics: quotes, news, alerts. Quotes accept a `?symbols=AAPL,MSFT`
filter — when present, the route subscribes only to symbol-scoped topics
on the hub *and* registers those symbols upstream with the AlpacaStreamer
(so we only burn an upstream subscription when somebody is listening).

Heartbeats: every 25s we send a `{"type":"ping"}` frame to keep proxies
from idling the connection. Browsers' native WebSocket ignores empty
frames; an explicit ping is more interoperable.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Iterable

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from ...core.auth import user_from_token
from ...core.config import settings
from ...core.streaming import hub, streamer

logger = logging.getLogger(__name__)
router = APIRouter()

HEARTBEAT_SECONDS = 25.0


async def _pump(ws: WebSocket, queues: list[asyncio.Queue]) -> None:
    """Multiplex N hub queues onto one WebSocket, with periodic pings."""
    pending: set[asyncio.Task] = set()

    def schedule_get(q: asyncio.Queue) -> asyncio.Task:
        task = asyncio.create_task(q.get())
        task._origin_queue = q  # type: ignore[attr-defined]
        return task

    for q in queues:
        pending.add(schedule_get(q))
    heartbeat = asyncio.create_task(asyncio.sleep(HEARTBEAT_SECONDS))
    pending.add(heartbeat)

    try:
        while True:
            done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                if task is heartbeat:
                    await ws.send_text(json.dumps({"type": "ping"}))
                    heartbeat = asyncio.create_task(asyncio.sleep(HEARTBEAT_SECONDS))
                    pending.add(heartbeat)
                    continue
                msg = task.result()
                await ws.send_text(json.dumps(msg, default=str))
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
