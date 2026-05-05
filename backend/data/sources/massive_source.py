"""Massive adapter — Polygon-compatible REST API at api.massive.com.

A single MASSIVE_API_KEY covers stock quotes, aggregates, options
snapshots, and the flow tape we derive from the options snapshot.
The endpoints + JSON shapes match Polygon.io exactly, so this module
is essentially a parameterized Polygon client.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from ...core.config import settings
from ...models.schemas import Quote
from ..normalizer import get_normalizer

logger = logging.getLogger(__name__)


class MassiveSource:
    def __init__(self) -> None:
        self._key = settings.massive_api_key
        self._base = settings.massive_base_url.rstrip("/")
        self._normalizer = get_normalizer()

    @property
    def configured(self) -> bool:
        return bool(self._key)

    async def _get(self, path: str, params: dict | None = None) -> Any | None:
        if not self.configured:
            return None
        url = f"{self._base}{path}"
        params = dict(params or {})
        params["apiKey"] = self._key
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url, params=params)
        except Exception as exc:
            logger.warning("massive request failed %s: %s", path, exc)
            return None
        if resp.status_code != 200:
            logger.warning("massive %s -> %s", path, resp.status_code)
            return None
        try:
            return resp.json()
        except Exception:
            return None

    # ── stock data ────────────────────────────────────────────────────

    async def get_stock_quote(self, symbol: str) -> Quote | None:
        sym = symbol.upper()
        data = await self._get(f"/v2/snapshot/locale/us/markets/stocks/tickers/{sym}")
        if not data:
            return None
        ticker = data.get("ticker") if isinstance(data, dict) else None
        if not ticker:
            return None
        last_trade = ticker.get("lastTrade") or {}
        day = ticker.get("day") or {}
        prev = ticker.get("prevDay") or {}
        price = _f(last_trade.get("p")) or _f(day.get("c"))
        if not price:
            return None
        prev_close = _f(prev.get("c"))
        change = price - prev_close if prev_close else 0.0
        change_pct = (change / prev_close * 100.0) if prev_close else 0.0
        q = Quote(
            symbol=sym,
            price=price,
            change=change,
            change_percent=change_pct,
            volume=int(_f(day.get("v")) or 0),
            day_high=_f(day.get("h")),
            day_low=_f(day.get("l")),
            previous_close=prev_close if prev_close else None,
            timestamp=datetime.now(timezone.utc),
        )
        try:
            self._normalizer.from_quote("massive", q)
        except Exception:
            pass
        return q

    async def aggregates(self, symbol: str, multiplier: int, timespan: str, from_: str, to: str) -> list[dict]:
        path = f"/v2/aggs/ticker/{symbol.upper()}/range/{multiplier}/{timespan}/{from_}/{to}"
        data = await self._get(path, {"limit": 5000, "adjusted": "true"})
        if not data:
            return []
        results = data.get("results") or []
        return [
            {
                "timestamp": datetime.fromtimestamp(int(r.get("t", 0)) / 1000, tz=timezone.utc).isoformat(),
                "open": _f(r.get("o")),
                "high": _f(r.get("h")),
                "low": _f(r.get("l")),
                "close": _f(r.get("c")),
                "volume": int(_f(r.get("v")) or 0),
            }
            for r in results
        ]

    async def market_status(self) -> dict:
        return await self._get("/v1/marketstatus/now") or {}

    async def ticker_details(self, symbol: str) -> dict:
        data = await self._get(f"/v3/reference/tickers/{symbol.upper()}")
        return (data or {}).get("results") or {}

    # ── options-derived flow tape ─────────────────────────────────────

    async def options_snapshot(self, underlying: str) -> list[dict]:
        """Fetch the full options snapshot for one underlying.

        Returns a list of contract dicts, each enriched with day volume,
        last trade, premium, IV, and Greeks. Used by the synthetic flow
        tape — large day volume + high premium ≈ institutional activity.
        """
        sym = underlying.upper()
        data = await self._get(f"/v3/snapshot/options/{sym}", {"limit": 250})
        if not data:
            return []
        results = data.get("results") or []
        out: list[dict] = []
        for c in results:
            details = c.get("details") or {}
            day = c.get("day") or {}
            last_trade = c.get("last_trade") or {}
            greeks = c.get("greeks") or {}
            try:
                strike = _f(details.get("strike_price"))
                expiry = details.get("expiration_date")
                contract_type = (details.get("contract_type") or "").lower()  # call|put
                price = _f(last_trade.get("price")) or _f(day.get("close"))
                size = int(_f(day.get("volume")) or 0)
                premium = (price * 100 * size) if (price is not None and size) else None
                out.append({
                    "ticker": details.get("ticker"),
                    "underlying": sym,
                    "type": contract_type,
                    "strike": strike,
                    "expiry": expiry,
                    "size": size,
                    "premium": premium,
                    "iv": _f(c.get("implied_volatility")),
                    "delta": _f(greeks.get("delta")),
                    "gamma": _f(greeks.get("gamma")),
                    "open_interest": int(_f(c.get("open_interest")) or 0),
                    "last_trade_ts": _ts_iso(last_trade.get("sip_timestamp")),
                })
            except Exception:
                continue
        return out


def _f(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _ts_iso(ns: Any) -> str:
    """Polygon-style nanosecond timestamps → ISO. Falls back to now."""
    if ns is None:
        return datetime.now(timezone.utc).isoformat()
    try:
        return datetime.fromtimestamp(int(ns) / 1e9, tz=timezone.utc).isoformat()
    except Exception:
        return datetime.now(timezone.utc).isoformat()
