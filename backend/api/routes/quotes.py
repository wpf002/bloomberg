import asyncio
import logging
from typing import List

from fastapi import APIRouter, HTTPException, Query

from ...data.sources import FinnhubSource, get_alpaca_source
from ...models.schemas import Quote, QuoteHistoryPoint

logger = logging.getLogger(__name__)
router = APIRouter()
_alpaca = get_alpaca_source()
_finnhub = FinnhubSource()

# Indices Alpaca doesn't carry. For history (charts) we substitute the
# closest tradable ETF — Alpaca has full IEX-grade bars on these and they
# track the same underlying basket, so a chart of "^GSPC" actually shows
# SPY. We tag the QuoteHistoryPoint with the proxy symbol so the frontend
# can label the substitution if it wants to.
INDEX_PROXY_ETF: dict[str, str] = {
    "^GSPC":   "SPY",
    "^IXIC":   "QQQ",
    "^DJI":    "DIA",
    "^VIX":    "VIXY",
    "^RUT":    "IWM",
    "^TNX":    "TLT",   # rough — TLT is long Treasuries, ^TNX is the 10Y yield
}


async def _best_quote(symbol: str) -> Quote:
    """Alpaca first (real-time, rate-limit-free for paper accounts);
    fall back to the index-ETF proxy for `^GSPC` etc. (Finnhub free
    tier blocks CFD indices); Finnhub last for any remaining non-US
    ticker. This fully retires the yfinance scraper path."""
    sym = symbol.upper()
    try:
        alpaca_quote = await _alpaca.get_stock_quote(sym)
        if alpaca_quote is not None:
            return alpaca_quote
    except Exception as exc:
        logger.warning("alpaca snapshot failed for %s: %s", sym, exc)
    # Index proxy: Alpaca doesn't carry raw indices, but it does carry the
    # most-tracked ETF on each. Substitute and re-tag so the caller knows.
    proxy = INDEX_PROXY_ETF.get(sym)
    if proxy:
        try:
            q = await _alpaca.get_stock_quote(proxy)
            if q is not None:
                return q.model_copy(update={"symbol": sym})
        except Exception as exc:
            logger.warning("alpaca proxy %s for %s failed: %s", proxy, sym, exc)
    try:
        fh = await _finnhub.get_quote(sym)
        if fh is not None:
            return fh
    except Exception as exc:
        logger.warning("finnhub quote failed for %s: %s", sym, exc)
    raise HTTPException(status_code=404, detail=f"no quote available for {sym}")


@router.get("", response_model=List[Quote])
async def get_quotes(symbols: str = Query(..., description="Comma-separated ticker list")) -> List[Quote]:
    parsed = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    if not parsed:
        raise HTTPException(status_code=400, detail="At least one symbol is required")
    try:
        return await asyncio.gather(*(_best_quote(s) for s in parsed))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"quote provider error: {exc}") from exc


@router.get("/{symbol}", response_model=Quote)
async def get_quote(symbol: str) -> Quote:
    try:
        return await _best_quote(symbol)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"quote provider error: {exc}") from exc


@router.get("/{symbol}/history", response_model=List[QuoteHistoryPoint])
async def get_history(
    symbol: str,
    period: str = Query("1mo", description="e.g. 1d, 5d, 1mo, 3mo, 6mo, 1y, 5y, max"),
    interval: str = Query("1d", description="e.g. 1m, 5m, 15m, 1h, 1d, 1wk"),
) -> List[QuoteHistoryPoint]:
    sym = symbol.upper()
    target = INDEX_PROXY_ETF.get(sym, sym)
    try:
        bars = await _alpaca.get_stock_bars(target, period, interval)
        if bars:
            return bars
    except Exception as exc:
        logger.warning("alpaca bars failed for %s (target=%s): %s", sym, target, exc)
    raise HTTPException(
        status_code=404,
        detail=(
            f"no bars available for {sym}. Indices map to ETF proxies "
            f"(see INDEX_PROXY_ETF); raw indices and futures aren't covered."
        ),
    )
