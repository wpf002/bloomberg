import asyncio
import logging
from typing import List

from fastapi import APIRouter, HTTPException, Query

from ...data.sources import FrankfurterSource
from ...models.schemas import FxQuote

logger = logging.getLogger(__name__)
router = APIRouter()
_frankfurter = FrankfurterSource()

DEFAULT_PAIRS = ["EURUSD", "GBPUSD", "USDJPY", "USDCHF", "USDCAD", "AUDUSD", "NZDUSD"]


@router.get("", response_model=List[FxQuote])
async def list_fx(
    pairs: str = Query(",".join(DEFAULT_PAIRS), description="Comma-separated ISO pairs, e.g. EURUSD,USDJPY"),
) -> List[FxQuote]:
    """ECB reference rates via Frankfurter (free, no key, end-of-day).
    Frankfurter publishes rates the ECB sets at 16:00 CET; for retail
    FX overview this is fine. Real-time intraday FX would require a paid
    feed (Polygon, Finnhub Premium, OANDA)."""
    parsed = [p.strip().upper() for p in pairs.split(",") if p.strip()]
    if not parsed:
        raise HTTPException(status_code=400, detail="At least one pair is required")
    results = await asyncio.gather(
        *(_frankfurter.get_fx_quote(p) for p in parsed),
        return_exceptions=True,
    )
    out: List[FxQuote] = []
    for pair, r in zip(parsed, results):
        if isinstance(r, Exception):
            logger.warning("FX fetch %s failed: %s", pair, r)
            continue
        if r is not None:
            out.append(r)
    return out


@router.get("/{pair}", response_model=FxQuote)
async def get_pair(pair: str) -> FxQuote:
    try:
        q = await _frankfurter.get_fx_quote(pair.upper())
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"frankfurter error: {exc}") from exc
    if q is None:
        raise HTTPException(status_code=404, detail=f"unknown pair {pair}")
    return q
