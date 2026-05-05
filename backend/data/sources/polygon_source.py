"""Polygon.io adapter — V2.6 supplement.

When POLYGON_API_KEY is set, Polygon's SIP-feed quotes and aggregates
become available alongside Alpaca's IEX-feed. Both stay routed through
the normalizer so provenance is preserved. Without the key every
method returns None / [] so callers fall back to Alpaca seamlessly.
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

POLY_BASE = "https://api.polygon.io"


class PolygonSource:
    def __init__(self) -> None:
        self._key = settings.polygon_api_key
        self._normalizer = get_normalizer()

    @property
    def configured(self) -> bool:
        return bool(self._key)

    async def _get(self, path: str, params: dict | None = None) -> Any | None:
        if not self.configured:
            return None
        url = f"{POLY_BASE}{path}"
        params = dict(params or {})
        params["apiKey"] = self._key
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url, params=params)
        except Exception as exc:
            logger.warning("polygon request failed %s: %s", path, exc)
            return None
        if resp.status_code != 200:
            logger.warning("polygon %s -> %s", path, resp.status_code)
            return None
        try:
            return resp.json()
        except Exception:
            return None

    async def get_stock_quote(self, symbol: str) -> Quote | None:
        """Single-symbol snapshot via /v2/snapshot/locale/us/markets/stocks/tickers."""
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
            self._normalizer.from_quote("polygon", q)
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
        data = await self._get("/v1/marketstatus/now")
        return data or {}

    async def ticker_details(self, symbol: str) -> dict:
        data = await self._get(f"/v3/reference/tickers/{symbol.upper()}")
        return (data or {}).get("results") or {}


def _f(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
