"""In-process pub/sub hub + Alpaca WebSocket bridge.

Architecture
------------
The frontend opens a WebSocket per topic — `quotes`, `news`, or `alerts`.
The `StreamHub` keeps an `asyncio.Queue` per WS client and broadcasts a
message to every queue subscribed to a topic. There is no Redis pubsub on
the data path: a single uvicorn process is plenty for retail-scale usage,
and Redis Streams is reserved for *durable* alert events (Phase 5.C) so
they survive a frontend reload.

The `AlpacaStreamer` opens *one* upstream connection to Alpaca's IEX
market-data WS and one to their news WS, multiplexes incoming messages
into the hub, and lets the alert evaluator listen on the same broadcast.
We never open one upstream socket per browser tab.

If Alpaca creds aren't configured, the streamer simulates quote ticks by
re-using the REST snapshot endpoint with a 4s heartbeat — enough to drive
the UI in dev so empty-state debugging isn't required for the WS path.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Iterable

import httpx

from .config import settings

logger = logging.getLogger(__name__)


# ───────────────────────── in-process hub ──────────────────────────────────

class StreamHub:
    """Topic-based broadcast across asyncio queues. One queue per subscriber.

    Subscribers should drain their queue continuously; we drop messages on
    full queues rather than blocking the publisher (a slow client must not
    stall everyone else).
    """

    def __init__(self) -> None:
        self._subs: dict[str, set[asyncio.Queue]] = {}
        self._lock = asyncio.Lock()

    async def subscribe(self, topic: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=256)
        async with self._lock:
            self._subs.setdefault(topic, set()).add(q)
        return q

    async def unsubscribe(self, topic: str, q: asyncio.Queue) -> None:
        async with self._lock:
            bucket = self._subs.get(topic)
            if not bucket:
                return
            bucket.discard(q)
            if not bucket:
                self._subs.pop(topic, None)

    def has_subscribers(self, topic: str) -> bool:
        bucket = self._subs.get(topic)
        return bool(bucket)

    async def publish(self, topic: str, payload: Any) -> None:
        bucket = self._subs.get(topic)
        if not bucket:
            return
        for q in list(bucket):
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                logger.debug("stream queue full for topic=%s; dropping message", topic)

    def topics(self) -> list[str]:
        return list(self._subs.keys())


hub = StreamHub()


# ─────────────────────── Alpaca upstream streamer ──────────────────────────

ALPACA_DATA_WS = "wss://stream.data.alpaca.markets/v2/iex"  # free IEX feed
ALPACA_NEWS_WS = "wss://stream.data.alpaca.markets/v1beta1/news"


class AlpacaStreamer:
    """Manages two long-lived WS connections (quotes + news) and republishes
    incoming messages on the in-process hub.

    Symbol subscriptions are demand-driven — when the first frontend WS
    asks for AAPL, we send a `subscribe` frame upstream; when the last one
    drops it, we send `unsubscribe`. Spec: https://alpaca.markets/docs/.
    """

    def __init__(self) -> None:
        self._quote_task: asyncio.Task | None = None
        self._news_task: asyncio.Task | None = None
        self._poll_task: asyncio.Task | None = None
        self._symbols: set[str] = set()
        self._symbols_lock = asyncio.Lock()
        self._quote_ws_subscribed: set[str] = set()
        self._stop = asyncio.Event()
        # Lazy import — websockets is optional at install time so the
        # smoke test (which only imports modules) doesn't pull a network
        # library transitively. Falls back to REST polling when missing.
        self._ws_lib = None

    def _enabled(self) -> bool:
        return bool(settings.alpaca_api_key and settings.alpaca_api_secret)

    async def start(self) -> None:
        if self._quote_task is not None:
            return
        try:
            import websockets  # type: ignore

            self._ws_lib = websockets
        except Exception:
            self._ws_lib = None

        if self._enabled() and self._ws_lib is not None:
            self._quote_task = asyncio.create_task(self._run_quote_ws(), name="alpaca-quotes-ws")
            self._news_task = asyncio.create_task(self._run_news_ws(), name="alpaca-news-ws")
        else:
            # REST-poll fallback so the UI shows ticking quotes even with no
            # creds / no `websockets` lib installed yet.
            self._poll_task = asyncio.create_task(self._run_quote_poll(), name="alpaca-quotes-poll")
        logger.info(
            "AlpacaStreamer started (mode=%s, creds=%s)",
            "ws" if self._ws_lib and self._enabled() else "poll-fallback",
            self._enabled(),
        )

    async def stop(self) -> None:
        self._stop.set()
        for t in (self._quote_task, self._news_task, self._poll_task):
            if t and not t.done():
                t.cancel()
        self._quote_task = self._news_task = self._poll_task = None

    async def add_symbols(self, symbols: Iterable[str]) -> None:
        cleaned = {s.upper() for s in symbols if s}
        if not cleaned:
            return
        async with self._symbols_lock:
            new = cleaned - self._symbols
            self._symbols.update(cleaned)
        if new and self._ws_lib and self._enabled():
            await self._send_quote_sub(new, subscribe=True)

    async def remove_symbols(self, symbols: Iterable[str]) -> None:
        cleaned = {s.upper() for s in symbols if s}
        async with self._symbols_lock:
            removed = self._symbols & cleaned
            self._symbols.difference_update(cleaned)
        if removed and self._ws_lib and self._enabled():
            await self._send_quote_sub(removed, subscribe=False)

    # ── upstream: quotes ────────────────────────────────────────────────

    async def _run_quote_ws(self) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            try:
                async with self._ws_lib.connect(ALPACA_DATA_WS, ping_interval=20) as ws:
                    await ws.send(
                        json.dumps(
                            {
                                "action": "auth",
                                "key": settings.alpaca_api_key,
                                "secret": settings.alpaca_api_secret,
                            }
                        )
                    )
                    self._quote_ws = ws
                    self._quote_ws_subscribed.clear()
                    async with self._symbols_lock:
                        if self._symbols:
                            await ws.send(
                                json.dumps(
                                    {"action": "subscribe", "trades": list(self._symbols), "quotes": list(self._symbols)}
                                )
                            )
                            self._quote_ws_subscribed = set(self._symbols)
                    backoff = 1.0
                    async for raw in ws:
                        try:
                            msgs = json.loads(raw)
                        except Exception:
                            continue
                        if not isinstance(msgs, list):
                            msgs = [msgs]
                        for m in msgs:
                            await self._dispatch_quote_msg(m)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("alpaca quote ws crashed: %s; reconnect in %.1fs", exc, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)

    async def _send_quote_sub(self, symbols: set[str], *, subscribe: bool) -> None:
        ws = getattr(self, "_quote_ws", None)
        if ws is None:
            return
        action = "subscribe" if subscribe else "unsubscribe"
        try:
            await ws.send(json.dumps({"action": action, "trades": list(symbols), "quotes": list(symbols)}))
            if subscribe:
                self._quote_ws_subscribed.update(symbols)
            else:
                self._quote_ws_subscribed.difference_update(symbols)
        except Exception as exc:
            logger.debug("could not %s upstream symbols=%s: %s", action, symbols, exc)

    async def _dispatch_quote_msg(self, m: dict) -> None:
        t = m.get("T")
        if t == "t":  # trade
            sym = (m.get("S") or "").upper()
            price = m.get("p")
            if sym and price:
                payload = {
                    "type": "trade",
                    "symbol": sym,
                    "price": float(price),
                    "size": int(m.get("s") or 0),
                    "timestamp": m.get("t") or datetime.now(timezone.utc).isoformat(),
                }
                await hub.publish("quotes", payload)
                await hub.publish(f"quotes:{sym}", payload)
        elif t == "q":  # quote
            sym = (m.get("S") or "").upper()
            bid = m.get("bp")
            ask = m.get("ap")
            if sym:
                payload = {
                    "type": "quote",
                    "symbol": sym,
                    "bid": float(bid or 0.0),
                    "ask": float(ask or 0.0),
                    "timestamp": m.get("t") or datetime.now(timezone.utc).isoformat(),
                }
                await hub.publish("quotes", payload)
                await hub.publish(f"quotes:{sym}", payload)

    # ── upstream: news ──────────────────────────────────────────────────

    async def _run_news_ws(self) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            try:
                async with self._ws_lib.connect(ALPACA_NEWS_WS, ping_interval=20) as ws:
                    await ws.send(
                        json.dumps(
                            {
                                "action": "auth",
                                "key": settings.alpaca_api_key,
                                "secret": settings.alpaca_api_secret,
                            }
                        )
                    )
                    await ws.send(json.dumps({"action": "subscribe", "news": ["*"]}))
                    backoff = 1.0
                    async for raw in ws:
                        try:
                            msgs = json.loads(raw)
                        except Exception:
                            continue
                        if not isinstance(msgs, list):
                            msgs = [msgs]
                        for m in msgs:
                            if m.get("T") != "n":
                                continue
                            await hub.publish(
                                "news",
                                {
                                    "id": str(m.get("id", "")),
                                    "headline": m.get("headline", ""),
                                    "summary": m.get("summary"),
                                    "url": m.get("url", ""),
                                    "source": m.get("source", "alpaca"),
                                    "symbols": m.get("symbols", []) or [],
                                    "published_at": m.get("created_at"),
                                },
                            )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("alpaca news ws crashed: %s; reconnect in %.1fs", exc, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)

    # ── REST poll fallback (creds missing or websockets lib absent) ────

    async def _run_quote_poll(self) -> None:
        from ..data.sources import get_alpaca_source

        alpaca = get_alpaca_source()
        while not self._stop.is_set():
            try:
                async with self._symbols_lock:
                    symbols = list(self._symbols)
                if symbols and alpaca.credentials_configured():
                    for sym in symbols:
                        q = await alpaca.get_stock_quote(sym)
                        if q is None:
                            continue
                        await hub.publish(
                            "quotes",
                            {
                                "type": "snapshot",
                                "symbol": q.symbol,
                                "price": q.price,
                                "change_percent": q.change_percent,
                                "timestamp": q.timestamp.isoformat(),
                            },
                        )
                        await hub.publish(
                            f"quotes:{q.symbol}",
                            {
                                "type": "snapshot",
                                "symbol": q.symbol,
                                "price": q.price,
                                "change_percent": q.change_percent,
                                "timestamp": q.timestamp.isoformat(),
                            },
                        )
                else:
                    # No creds — emit jittered synthetic ticks for active
                    # subscriptions so the UI flow is testable in dev.
                    for sym in symbols:
                        await hub.publish(
                            f"quotes:{sym}",
                            {
                                "type": "synthetic",
                                "symbol": sym,
                                "price": round(100.0 + random.random() * 5, 2),
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                            },
                        )
            except Exception as exc:
                logger.debug("poll loop error: %s", exc)
            await asyncio.sleep(4.0)


streamer = AlpacaStreamer()


# ─────────────────────── helpers used by the routes ─────────────────────────

async def iter_topic(topic: str) -> AsyncIterator[Any]:
    """Yield messages for a single subscriber until it's cancelled."""
    q = await hub.subscribe(topic)
    try:
        while True:
            msg = await q.get()
            yield msg
    finally:
        await hub.unsubscribe(topic, q)
