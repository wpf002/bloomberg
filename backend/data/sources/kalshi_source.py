"""Kalshi adapter — read-only public endpoints (no auth).

Kalshi is a federally regulated US prediction-market exchange. We use
the public market list to surface macro contracts (FOMC decisions,
CPI prints, recession-by-year, etc.). Probabilities come from the
yes_bid / yes_ask midpoint scaled to the [0, 1] interval.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from ..normalizer import get_normalizer

logger = logging.getLogger(__name__)

KALSHI_BASE = "https://trading-api.kalshi.com/trade-api/v2"


class KalshiSource:
    def __init__(self) -> None:
        self._normalizer = get_normalizer()

    async def _get(self, path: str, params: dict | None = None) -> Any | None:
        url = f"{KALSHI_BASE}{path}"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url, params=params or {})
        except Exception as exc:
            logger.warning("kalshi request failed %s: %s", path, exc)
            return None
        if resp.status_code != 200:
            logger.warning("kalshi %s -> %s", path, resp.status_code)
            return None
        try:
            return resp.json()
        except Exception:
            return None

    async def search(self, query: str, limit: int = 25) -> list[dict]:
        data = await self._get("/markets", {"limit": limit, "status": "open"})
        markets = (data or {}).get("markets", []) if isinstance(data, dict) else []
        q = (query or "").lower()
        if q:
            markets = [m for m in markets if q in (m.get("title") or "").lower() or q in (m.get("category") or "").lower()]
        return self._normalize_many(markets[:limit])

    async def macro(self, limit: int = 25) -> list[dict]:
        keywords = ["FED", "CPI", "INFLATION", "RECESSION", "RATE", "FOMC"]
        all_markets = []
        data = await self._get("/markets", {"limit": 200, "status": "open"})
        markets = (data or {}).get("markets", []) if isinstance(data, dict) else []
        for m in markets:
            title = (m.get("title") or "").upper()
            if any(k in title for k in keywords):
                all_markets.append(m)
        return self._normalize_many(all_markets[:limit])

    async def equity(self, limit: int = 25) -> list[dict]:
        keywords = ["S&P", "STOCK", "VIX", "DOW", "NASDAQ", "MARKET"]
        out = []
        data = await self._get("/markets", {"limit": 200, "status": "open"})
        markets = (data or {}).get("markets", []) if isinstance(data, dict) else []
        for m in markets:
            title = (m.get("title") or "").upper()
            if any(k in title for k in keywords):
                out.append(m)
        return self._normalize_many(out[:limit])

    async def upcoming_events(self, limit: int = 25) -> list[dict]:
        data = await self._get("/markets", {"limit": 200, "status": "open"})
        markets = (data or {}).get("markets", []) if isinstance(data, dict) else []
        rows = self._normalize_many(markets)
        rows.sort(key=lambda r: r.get("days_to_resolution") or 9999)
        return rows[:limit]

    def _normalize_many(self, items: list[dict]) -> list[dict]:
        out: list[dict] = []
        seen: set[str] = set()
        for m in items:
            ticker = m.get("ticker") or m.get("event_ticker") or ""
            if not ticker or ticker in seen:
                continue
            seen.add(ticker)
            try:
                bid = _f(m.get("yes_bid"))
                ask = _f(m.get("yes_ask"))
                # Kalshi prices are in cents (0..100). Mid = average of bid/ask
                # if both present, otherwise whichever exists.
                if bid is not None and ask is not None:
                    prob = (bid + ask) / 200.0
                elif bid is not None:
                    prob = bid / 100.0
                elif ask is not None:
                    prob = ask / 100.0
                else:
                    prob = None
                resolution = m.get("close_time") or m.get("expiration_time")
                row = {
                    "id": ticker,
                    "slug": ticker.lower(),
                    "question": m.get("title") or m.get("subtitle") or ticker,
                    "probability": prob,
                    "volume_24h": _f(m.get("volume_24h")),
                    "volume_total": _f(m.get("volume")),
                    "liquidity": _f(m.get("liquidity")),
                    "resolution_date": resolution,
                    "days_to_resolution": _days_to(resolution),
                    "category": m.get("category"),
                    "source": "kalshi",
                    "url": f"https://kalshi.com/markets/{ticker.lower()}",
                }
                out.append(row)
                try:
                    self._normalizer.normalize(
                        source="kalshi",
                        symbol="PRED:" + ticker.upper(),
                        series_id="probability",
                        value=prob if prob is not None else 0.0,
                        timestamp=datetime.now(timezone.utc),
                    )
                except Exception:
                    pass
            except Exception as exc:
                logger.debug("kalshi normalize skipping market: %s", exc)
        return out


def _f(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _days_to(iso: str | None) -> int | None:
    if not iso:
        return None
    try:
        ts = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        delta = (ts - datetime.now(timezone.utc)).total_seconds() / 86400.0
        return int(round(delta))
    except Exception:
        return None
