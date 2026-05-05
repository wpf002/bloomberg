"""V2.6 — supplementary market-data endpoints.

  GET /api/market/short-interest/{symbol}     FINRA via Nasdaq Data Link
  GET /api/market/insider/{symbol}            insider transactions
  GET /api/market/institutional/{symbol}      13F aggregates
  GET /api/market/iv/{symbol}                 IV rank + IV percentile

When NASDAQ_DATA_LINK_API_KEY is missing, those routes return
needs_key payloads so the frontend can show a configure message.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter

from ...data.sources.cboe_source import get_cboe_source
from ...data.sources.nasdaq_data_link_source import NasdaqDataLinkSource

router = APIRouter()
logger = logging.getLogger(__name__)
_ndl = NasdaqDataLinkSource()
_cboe = get_cboe_source()


@router.get("/short-interest/{symbol}")
async def short_interest(symbol: str) -> dict:
    if not _ndl.configured:
        return {"items": [], "needs_key": True, "symbol": symbol.upper()}
    items = await _ndl.short_interest(symbol)
    return {"items": items, "needs_key": False, "symbol": symbol.upper()}


@router.get("/insider/{symbol}")
async def insider(symbol: str) -> dict:
    if not _ndl.configured:
        return {"items": [], "needs_key": True, "symbol": symbol.upper()}
    items = await _ndl.insider_transactions(symbol)
    return {"items": items, "needs_key": False, "symbol": symbol.upper()}


@router.get("/institutional/{symbol}")
async def institutional(symbol: str) -> dict:
    if not _ndl.configured:
        return {"items": [], "needs_key": True, "symbol": symbol.upper()}
    items = await _ndl.institutional_ownership(symbol)
    return {"items": items, "needs_key": False, "symbol": symbol.upper()}


@router.get("/iv/{symbol}")
async def iv(symbol: str) -> dict:
    """IV Rank + IV Percentile from the local CBOE rolling buffer.

    The buffer warms up as the options panel polls /api/options/{sym}
    and pushes the per-day at-the-money IV into the buffer. Until the
    buffer has at least 5 datapoints both stats are null.
    """
    sym = symbol.upper()
    return {
        "symbol": sym,
        "iv_rank": _cboe.iv_rank(sym),
        "iv_percentile": _cboe.iv_percentile(sym),
    }
