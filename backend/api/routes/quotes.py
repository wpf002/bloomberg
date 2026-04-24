import asyncio
import logging
from typing import List

from fastapi import APIRouter, HTTPException, Query

from ...data.sources import YFinanceSource, get_alpaca_source
from ...models.schemas import Quote, QuoteHistoryPoint

logger = logging.getLogger(__name__)
router = APIRouter()
_yf = YFinanceSource()
_alpaca = get_alpaca_source()


async def _best_quote(symbol: str) -> Quote:
    """Alpaca snapshot first (real-time, rate-limit-free for paper accounts),
    falling back to yfinance for symbols Alpaca doesn't carry — indices
    (^VIX), futures (CL=F), currency indices (DX-Y.NYB), most non-US tickers.
    Yahoo is scraped and gets throttled under load; keep it as a fallback
    only, not the primary."""
    sym = symbol.upper()
    try:
        alpaca_quote = await _alpaca.get_stock_quote(sym)
        if alpaca_quote is not None:
            return alpaca_quote
    except Exception as exc:
        logger.warning("alpaca snapshot failed for %s: %s", sym, exc)
    return await _yf.get_quote(sym)


@router.get("", response_model=List[Quote])
async def get_quotes(symbols: str = Query(..., description="Comma-separated ticker list")) -> List[Quote]:
    parsed = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    if not parsed:
        raise HTTPException(status_code=400, detail="At least one symbol is required")
    try:
        return await asyncio.gather(*(_best_quote(s) for s in parsed))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"quote provider error: {exc}") from exc


@router.get("/{symbol}", response_model=Quote)
async def get_quote(symbol: str) -> Quote:
    try:
        return await _best_quote(symbol)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"quote provider error: {exc}") from exc


@router.get("/{symbol}/history", response_model=List[QuoteHistoryPoint])
async def get_history(
    symbol: str,
    period: str = Query("1mo", description="e.g. 1d, 5d, 1mo, 3mo, 6mo, 1y, 5y, max"),
    interval: str = Query("1d", description="e.g. 1m, 5m, 15m, 1h, 1d, 1wk"),
) -> List[QuoteHistoryPoint]:
    sym = symbol.upper()
    # Alpaca bars first — real-time IEX, no rate limit on paper tier.
    try:
        bars = await _alpaca.get_stock_bars(sym, period, interval)
        if bars:
            return bars
    except Exception as exc:
        logger.warning("alpaca bars failed for %s: %s", sym, exc)
    # yfinance fallback for indices / non-US / anything Alpaca doesn't carry.
    try:
        return await _yf.get_history(sym, period=period, interval=interval)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"history provider error: {exc}") from exc
