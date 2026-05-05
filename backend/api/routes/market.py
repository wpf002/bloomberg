"""V2.6 — supplementary market-data endpoints.

  GET /api/market/iv/{symbol}  IV rank + IV percentile from CBOE buffer

The IV buffer is fed by the options chain endpoint on every fetch, so
the ranking warms up after a handful of polls. Other supplementary
data sources (short interest, insider, institutional ownership) were
removed when their upstream provider was dropped.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter

from ...data.sources.cboe_source import get_cboe_source

router = APIRouter()
logger = logging.getLogger(__name__)
_cboe = get_cboe_source()


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
