"""V2.5 — Prediction-market consensus from Polymarket + Kalshi.

Routes:
  GET /api/predictions/macro     macro contracts (Fed, CPI, recession)
  GET /api/predictions/markets   broad equity / volatility contracts
  GET /api/predictions/events    soonest-resolving high-impact events
  GET /api/predictions/search    keyword search across both sources

All endpoints merge results from both sources and dedupe by slug.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter

from ...data.sources.kalshi_source import KalshiSource
from ...data.sources.polymarket_source import PolymarketSource

router = APIRouter()
logger = logging.getLogger(__name__)

_poly = PolymarketSource()
_kalshi = KalshiSource()


def _merge(rows_a: list[dict], rows_b: list[dict]) -> list[dict]:
    seen = set()
    out: list[dict] = []
    for r in (rows_a or []) + (rows_b or []):
        key = (r.get("source"), r.get("id") or r.get("slug"))
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


async def _safe(coro, default):
    try:
        return await coro
    except Exception as exc:
        logger.debug("predictions source failed: %s", exc)
        return default


@router.get("/macro")
async def macro_contracts() -> dict[str, Any]:
    poly, kalshi = await asyncio.gather(_safe(_poly.macro(25), []), _safe(_kalshi.macro(25), []))
    rows = _merge(poly, kalshi)
    rows.sort(key=lambda r: (r.get("days_to_resolution") or 9999, -(r.get("volume_24h") or 0)))
    return {"items": rows, "count": len(rows)}


@router.get("/markets")
async def market_contracts() -> dict[str, Any]:
    poly, kalshi = await asyncio.gather(_safe(_poly.equity(25), []), _safe(_kalshi.equity(25), []))
    rows = _merge(poly, kalshi)
    rows.sort(key=lambda r: (r.get("days_to_resolution") or 9999, -(r.get("volume_24h") or 0)))
    return {"items": rows, "count": len(rows)}


@router.get("/events")
async def upcoming_events() -> dict[str, Any]:
    poly, kalshi = await asyncio.gather(
        _safe(_poly.upcoming_events(20), []),
        _safe(_kalshi.upcoming_events(20), []),
    )
    rows = _merge(poly, kalshi)
    rows.sort(key=lambda r: r.get("days_to_resolution") or 9999)
    return {"items": rows[:30], "count": len(rows)}


@router.get("/search")
async def search(q: str = "", limit: int = 20) -> dict[str, Any]:
    if not q:
        return {"items": [], "count": 0}
    poly, kalshi = await asyncio.gather(_safe(_poly.search(q, limit), []), _safe(_kalshi.search(q, limit), []))
    rows = _merge(poly, kalshi)
    return {"items": rows, "count": len(rows)}
