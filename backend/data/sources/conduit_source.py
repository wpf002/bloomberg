"""Market data via Conduit, run as a subprocess.

Conduit is a TypeScript library that fronts several market data vendors behind
one schema, with failover between your own keys and symbol resolution across
their differing conventions. It cannot be imported from Python, so it ships a
bridge: a Node process that speaks newline-delimited JSON on stdin and stdout.

This source spawns that bridge and satisfies the same interface as
``AlpacaSource`` and ``MassiveSource``, so it drops in behind ``get_stock_quote``
without any caller changing. It is **off unless ``CONDUIT_BRIDGE`` points at the
built bridge**, so importing this module changes nothing by itself.

Why a subprocess and not a socket: nothing listens, so there is no port to
collide with and no surface to secure, and the process dies with this one.
Market data goes vendor -> bridge -> this process's pipe, all on one machine.

Timestamps arrive as decimal strings. JSON has no 64-bit integer type and a
nanosecond epoch does not fit a double, so the bridge sends them as text.

Prices are the same numbers ``AlpacaSource`` already returns. Both read
``prevDailyBar.c`` from Alpaca's snapshot on ``feed=iex``, so switching a caller
to Conduit does not move any displayed price. Verified independently on
2026-09-28: Conduit's ``lastPx`` is within 0.01% of Yahoo across AAPL, MSFT, SPY,
NVDA and BRK.B, with no scaling or field-mapping error.

One caveat that predates Conduit and is unchanged by it: on the free IEX plan
``previous_close`` sits 0-5 cents from the official close, because IEX is one
venue and its daily bar cannot contain the closing auction where the official
close is struck. ``change`` and ``change_pct`` are computed from it, so both are
a few cents off what other sources show. A paid SIP plan resolves it; no
computation does.

The bridge refuses to start against Alpaca's test stream, which quotes a symbol
called FAKEPACA at invented prices, so a misconfiguration cannot silently feed
this application fiction.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from itertools import count
from typing import Any

from ...models.schemas import Quote

logger = logging.getLogger(__name__)

# Nanoseconds per second, for turning a bridge timestamp into a datetime.
_NS_PER_SEC = 1_000_000_000

_DEFAULT_TIMEOUT = 15.0


class ConduitUnavailable(RuntimeError):
    """The bridge is not configured, or died and could not be restarted."""


class ConduitSource:
    """Quotes from whichever of your configured vendors Conduit picks."""

    name = "conduit"

    def __init__(
        self,
        bridge_path: str | None = None,
        node_path: str | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        self._bridge_path = bridge_path if bridge_path is not None else os.getenv("CONDUIT_BRIDGE")
        self._node_path = node_path or os.getenv("CONDUIT_NODE", "node")
        self._timeout = timeout

        self._proc: asyncio.subprocess.Process | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._ids = count(1)
        self._spawn_lock = asyncio.Lock()
        self._ready: dict[str, Any] | None = None

    # ------------------------------------------------------------ environment

    #: This repo's credential variable names, mapped to the ones Conduit's bridge reads.
    _ENV_ALIASES = {
        "ALPACA_API_KEY_ID": "ALPACA_API_KEY",
        "ALPACA_API_SECRET_KEY": "ALPACA_API_SECRET",
    }

    #: Alpaca feed names that serve invented prices. ``test`` quotes a symbol called FAKEPACA.
    _SYNTHETIC_FEEDS = frozenset({"test", "sandbox"})

    def _bridge_env(self) -> dict[str, str]:
        """The environment the bridge is spawned with.

        The bridge is a separate program and reads ``ALPACA_API_KEY_ID`` /
        ``ALPACA_API_SECRET_KEY``; this repo has held the same credentials as
        ``ALPACA_API_KEY`` / ``ALPACA_API_SECRET`` since before Conduit existed.
        Translating here means one place to rotate a key instead of two, and it
        means setting ``CONDUIT_BRIDGE`` is genuinely all that turning Conduit on
        requires. Without it the bridge starts with no providers and exits.

        A name the caller set explicitly is left alone — they meant it.
        """
        env = dict(os.environ)
        for bridge_name, local_name in self._ENV_ALIASES.items():
            if env.get(bridge_name):
                continue
            value = env.get(local_name)
            if value:
                env[bridge_name] = value

        # The bridge refuses a sandbox feed on its own. Not forwarding one means this application
        # never even asks for prices nobody traded at.
        if env.get("ALPACA_FEED", "").strip().lower() in self._SYNTHETIC_FEEDS:
            env.pop("ALPACA_FEED", None)

        return env

    # ------------------------------------------------------------------ status

    def _enabled(self) -> bool:
        return bool(self._bridge_path) and os.path.exists(self._bridge_path or "")

    def credentials_configured(self) -> bool:
        """Conduit holds the credentials itself, in its own environment."""
        return self._enabled()

    @property
    def providers(self) -> list[str]:
        """Vendors the bridge reported at startup. Empty until it has spawned."""
        return list((self._ready or {}).get("providers", []))

    # --------------------------------------------------------------- lifecycle

    async def _ensure_proc(self) -> asyncio.subprocess.Process:
        if not self._enabled():
            raise ConduitUnavailable("CONDUIT_BRIDGE is unset or does not exist")

        async with self._spawn_lock:
            if self._proc is not None and self._proc.returncode is None:
                return self._proc

            logger.info("Conduit bridge: spawning %s", self._bridge_path)
            self._proc = await asyncio.create_subprocess_exec(
                self._node_path,
                self._bridge_path or "",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=self._bridge_env(),
            )
            self._reader_task = asyncio.create_task(self._read_loop(self._proc))

            # The bridge announces itself before accepting requests; waiting for
            # that turns "no keys configured" into an error here rather than a
            # timeout on the first quote.
            try:
                self._ready = await asyncio.wait_for(self._await_ready(), timeout=self._timeout)
            except (asyncio.TimeoutError, ConduitUnavailable) as exc:
                await self._kill()
                raise ConduitUnavailable(f"bridge did not become ready: {exc}") from exc

            logger.info("Conduit bridge ready, providers=%s", self.providers)
            return self._proc

    async def _await_ready(self) -> dict[str, Any]:
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        # id 0 is reserved for unsolicited frames: `ready`, and errors with no id.
        self._pending[0] = future
        return await future

    async def _read_loop(self, proc: asyncio.subprocess.Process) -> None:
        """Dispatches every response to whoever is waiting on its id."""
        assert proc.stdout is not None
        try:
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    logger.warning("Conduit bridge: unparseable line %r", line[:120])
                    continue

                kind = message.get("type")
                if kind == "ready":
                    self._resolve(0, message)
                    continue
                # A subscription's messages share its id; this source only makes
                # one-shot requests, so anything not awaited is dropped.
                self._resolve(int(message.get("id", 0)), message)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Conduit bridge reader failed")
        finally:
            # Nobody is coming; fail every waiter rather than hanging them.
            for future in list(self._pending.values()):
                if not future.done():
                    future.set_exception(ConduitUnavailable("bridge exited"))
            self._pending.clear()

    def _resolve(self, request_id: int, message: dict[str, Any]) -> None:
        future = self._pending.pop(request_id, None)
        if future is not None and not future.done():
            future.set_result(message)

    async def _request(self, op: str, **fields: Any) -> dict[str, Any]:
        proc = await self._ensure_proc()
        assert proc.stdin is not None

        request_id = next(self._ids)
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future

        proc.stdin.write((json.dumps({"id": request_id, "op": op, **fields}) + "\n").encode())
        await proc.stdin.drain()

        try:
            message = await asyncio.wait_for(future, timeout=self._timeout)
        except asyncio.TimeoutError:
            self._pending.pop(request_id, None)
            raise ConduitUnavailable(f"{op} timed out after {self._timeout}s") from None

        if message.get("type") == "error":
            raise ConduitUnavailable(f"{op} failed: {message.get('code')}: {message.get('message')}")
        return message

    async def aclose(self) -> None:
        if self._proc is None:
            return
        try:
            if self._proc.returncode is None and self._proc.stdin is not None:
                self._proc.stdin.close()
                await asyncio.wait_for(self._proc.wait(), timeout=5.0)
        except (asyncio.TimeoutError, ProcessLookupError, ConnectionResetError):
            await self._kill()
        finally:
            if self._reader_task is not None:
                self._reader_task.cancel()
            self._proc = None
            self._reader_task = None
            self._ready = None

    async def _kill(self) -> None:
        if self._proc is not None and self._proc.returncode is None:
            try:
                self._proc.kill()
            except ProcessLookupError:
                pass
        if self._reader_task is not None:
            self._reader_task.cancel()
        self._proc = None
        self._reader_task = None

    # ------------------------------------------------------------------ quotes

    async def get_stock_quote(self, symbol: str) -> Quote | None:
        """Full Quote for one symbol, or None when Conduit has no data for it.

        Returns None rather than raising so callers can fall back to another
        source, matching AlpacaSource and MassiveSource.
        """
        quotes = await self.get_stock_quotes([symbol])
        return quotes.get(symbol)

    async def get_stock_quotes(self, symbols: list[str]) -> dict[str, Quote]:
        """Several symbols in one request, which is what the vendor endpoints take."""
        if not symbols:
            return {}
        try:
            message = await self._request("summary", symbols=list(symbols))
        except ConduitUnavailable as exc:
            logger.warning("Conduit summary %s: %s", ",".join(symbols), exc)
            return {}

        out: dict[str, Quote] = {}
        for row in message.get("data") or []:
            quote = _to_quote(row)
            if quote is not None:
                out[quote.symbol] = quote
        return out

    async def health(self) -> dict[str, Any]:
        """Per-vendor health as Conduit sees it, for a status endpoint."""
        try:
            return (await self._request("health")).get("data") or {}
        except ConduitUnavailable as exc:
            return {"error": str(exc)}


def _to_quote(row: dict[str, Any]) -> Quote | None:
    """One InstrumentSnapshot to a Quote, or None if there is no usable price."""
    day = row.get("day") or {}
    price = _pick_float(row.get("lastPx"), day.get("close"))
    if price is None or price <= 0:
        return None

    prev_close = _pick_float(row.get("prevClose"))
    change = price - prev_close if prev_close else 0.0
    change_percent = (change / prev_close * 100.0) if prev_close else 0.0

    return Quote(
        symbol=str(row.get("symbol") or ""),
        price=price,
        change=change,
        change_percent=change_percent,
        volume=int(day.get("volume") or 0),
        day_high=_pick_float(day.get("high")),
        day_low=_pick_float(day.get("low")),
        previous_close=prev_close,
        timestamp=_ns_to_datetime(row.get("tsEvent")),
    )


def _pick_float(*candidates: Any) -> float | None:
    for value in candidates:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
    return None


def _ns_to_datetime(value: Any) -> datetime:
    """Decimal-string nanoseconds to a datetime, falling back to now."""
    try:
        ns = int(value)
    except (TypeError, ValueError):
        return datetime.now(timezone.utc)
    return datetime.fromtimestamp(ns / _NS_PER_SEC, tz=timezone.utc)


_conduit_singleton: ConduitSource | None = None


def get_conduit_source() -> ConduitSource:
    """Shared process-wide ConduitSource; one bridge subprocess, not one per call."""
    global _conduit_singleton
    if _conduit_singleton is None:
        _conduit_singleton = ConduitSource()
    return _conduit_singleton
