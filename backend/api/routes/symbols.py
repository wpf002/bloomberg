"""Symbol search — autocomplete for the command bar.

Pulls Alpaca's active-equity asset list (~12k rows, cached 24h in
`AlpacaSource.list_active_assets`) and ranks matches against a query
prefix. Falls back to Finnhub's `/search` when Alpaca isn't configured
or doesn't carry the requested name.
"""

from __future__ import annotations

import logging
from typing import List

import httpx
from fastapi import APIRouter, Query

from ...core.config import settings
from ...data.sources import get_alpaca_source

logger = logging.getLogger(__name__)
router = APIRouter()
_alpaca = get_alpaca_source()


def _rank(asset: dict, q: str) -> int:
    """Lower is better. Ranking: symbol-exact (0) → symbol-prefix (1)
    → name-prefix (2) → symbol-substring (3) → name-substring (4)."""
    sym = (asset.get("symbol") or "").upper()
    name = (asset.get("name") or "").upper()
    if sym == q:
        return 0
    if sym.startswith(q):
        return 1
    if name.startswith(q):
        return 2
    if q in sym:
        return 3
    if q in name:
        return 4
    return 99


@router.get("/search")
async def search_symbols(
    q: str = Query(..., min_length=1, max_length=20),
    limit: int = Query(8, ge=1, le=50),
) -> List[dict]:
    """Return up to `limit` symbol matches for `q`.

    Result shape: `[{ "symbol": "AAPL", "name": "Apple Inc.", "exchange": "NASDAQ" }, ...]`
    Uppercase the query before ranking so case doesn't matter.
    """
    upper = q.strip().upper()
    if not upper:
        return []

    # Primary: Alpaca's full asset list — covers most US equities + ETFs.
    assets: list[dict] = []
    if _alpaca.credentials_configured():
        try:
            assets = await _alpaca.list_active_assets()
        except Exception as exc:
            logger.debug("alpaca asset list failed: %s", exc)

    if assets:
        scored = [(asset, _rank(asset, upper)) for asset in assets]
        hits = [a for a, r in scored if r < 99]
        hits.sort(key=lambda a: (_rank(a, upper), len(a.get("symbol") or "")))
        if hits:
            return [
                {
                    "symbol": a.get("symbol"),
                    "name": a.get("name"),
                    "exchange": a.get("exchange"),
                }
                for a in hits[:limit]
            ]

    # Fallback: Finnhub `/search` — covers indices and some non-US tickers
    # Alpaca doesn't carry. Free tier is 60 req/min.
    if settings.finnhub_api_key:
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.get(
                    "https://finnhub.io/api/v1/search",
                    params={"q": upper, "token": settings.finnhub_api_key},
                )
            if resp.status_code == 200:
                payload = resp.json() or {}
                results = payload.get("result") or []
                return [
                    {
                        "symbol": (r.get("symbol") or "").upper(),
                        "name": r.get("description") or "",
                        "exchange": r.get("type") or "",
                    }
                    for r in results[:limit]
                    if r.get("symbol")
                ]
        except Exception as exc:
            logger.debug("finnhub search fallback failed: %s", exc)

    return []
