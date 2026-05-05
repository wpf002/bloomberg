"""Polymarket adapter — public Gamma REST API.

Polymarket exposes prices as 0..1 probabilities, plus volume and
liquidity. No auth required for the read-only "gamma" endpoints we
use here. The shape we emit is normalized so PolymarketSource and
KalshiSource can be merged in the route layer without per-source
branching.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from ..normalizer import get_normalizer

logger = logging.getLogger(__name__)

POLY_BASE = "https://gamma-api.polymarket.com"


class PolymarketSource:
    def __init__(self) -> None:
        self._normalizer = get_normalizer()

    async def _get(self, path: str, params: dict | None = None) -> Any | None:
        url = f"{POLY_BASE}{path}"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url, params=params or {})
        except Exception as exc:
            logger.warning("polymarket request failed %s: %s", path, exc)
            return None
        if resp.status_code != 200:
            logger.warning("polymarket %s -> %s", path, resp.status_code)
            return None
        try:
            return resp.json()
        except Exception:
            return None

    async def search(self, query: str, limit: int = 25) -> list[dict]:
        data = await self._get("/markets", {"limit": limit, "search": query, "active": "true"})
        return self._normalize_many(data or [])

    async def macro(self, limit: int = 25) -> list[dict]:
        # Tag IDs aren't documented exhaustively; fall back to keyword search
        # across the macro-relevant markets.
        keywords = ["fed", "rate", "cpi", "inflation", "recession"]
        out: list[dict] = []
        for kw in keywords:
            data = await self._get("/markets", {"limit": limit, "search": kw, "active": "true"})
            for m in data or []:
                out.append(m)
        return self._normalize_many(out)

    async def equity(self, limit: int = 25) -> list[dict]:
        keywords = ["S&P", "stock market", "vix", "Dow", "nasdaq"]
        out: list[dict] = []
        for kw in keywords:
            data = await self._get("/markets", {"limit": limit, "search": kw, "active": "true"})
            for m in data or []:
                out.append(m)
        return self._normalize_many(out)

    async def upcoming_events(self, limit: int = 25) -> list[dict]:
        data = await self._get("/markets", {"limit": limit, "active": "true", "closed": "false"})
        rows = self._normalize_many(data or [])
        rows.sort(key=lambda r: r.get("days_to_resolution") or 9999)
        return rows[:limit]

    def _normalize_many(self, items: list[dict]) -> list[dict]:
        out: list[dict] = []
        seen: set[str] = set()
        for m in items:
            slug = m.get("slug") or m.get("id") or ""
            if not slug or slug in seen:
                continue
            seen.add(slug)
            try:
                # Polymarket markets often have multiple "outcomes"; we pick
                # the YES side when present, otherwise the first listed.
                price = None
                outcomes = m.get("outcomePrices") or m.get("outcome_prices")
                if isinstance(outcomes, list) and outcomes:
                    try:
                        price = float(outcomes[0])
                    except (TypeError, ValueError):
                        price = None
                if price is None:
                    p_raw = m.get("lastTradePrice") or m.get("last_trade_price")
                    try:
                        price = float(p_raw) if p_raw is not None else None
                    except (TypeError, ValueError):
                        price = None
                resolution = m.get("endDate") or m.get("end_date")
                days = _days_to(resolution)
                row = {
                    "id": str(m.get("id") or slug),
                    "slug": slug,
                    "question": m.get("question") or m.get("description") or m.get("title") or slug,
                    "probability": price,
                    "volume_24h": _f(m.get("volume24hr") or m.get("volume_24hr") or m.get("volume24h")),
                    "volume_total": _f(m.get("volume") or m.get("totalVolume")),
                    "liquidity": _f(m.get("liquidity")),
                    "resolution_date": resolution,
                    "days_to_resolution": days,
                    "category": m.get("category") or m.get("group_slug"),
                    "source": "polymarket",
                    "url": f"https://polymarket.com/markets/{slug}",
                }
                out.append(row)
                try:
                    self._normalizer.normalize(
                        source="polymarket",
                        symbol="PRED:" + slug.upper(),
                        series_id="probability",
                        value=row["probability"] if row["probability"] is not None else 0.0,
                        timestamp=datetime.now(timezone.utc),
                    )
                except Exception:
                    pass
            except Exception as exc:
                logger.debug("polymarket normalize skipping market: %s", exc)
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
