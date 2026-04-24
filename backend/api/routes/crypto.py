import asyncio
import logging
from typing import List

from fastapi import APIRouter, HTTPException, Query

from ...data.sources import YFinanceSource, get_alpaca_source
from ...models.schemas import CryptoQuote

logger = logging.getLogger(__name__)
router = APIRouter()
_yf = YFinanceSource()
_alpaca = get_alpaca_source()

DEFAULT_SYMBOLS = ["BTC-USD", "ETH-USD", "SOL-USD", "XRP-USD", "ADA-USD"]


async def _best_crypto_quote(symbol: str) -> CryptoQuote | None:
    """Alpaca's crypto snapshot endpoint first, yfinance fallback.
    yfinance is scraping Yahoo and gets rate-limited under load —
    Alpaca is the stable path."""
    sym = symbol.upper()
    try:
        q = await _alpaca.get_crypto_quote(sym)
        if q and q.price > 0:
            return CryptoQuote(
                symbol=sym,
                price=q.price,
                change_24h=q.change,
                change_percent_24h=q.change_percent,
                volume_24h=float(q.volume),
                timestamp=q.timestamp,
            )
    except Exception as exc:
        logger.debug("alpaca crypto %s failed: %s", sym, exc)
    try:
        return await _yf.get_crypto_quote(sym)
    except Exception as exc:
        logger.warning("crypto fallback failed for %s: %s", sym, exc)
        return None


@router.get("", response_model=List[CryptoQuote])
async def list_crypto(
    symbols: str = Query(
        ",".join(DEFAULT_SYMBOLS),
        description="Comma-separated crypto pair tickers (e.g. BTC-USD,ETH-USD)",
    ),
) -> List[CryptoQuote]:
    parsed = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    if not parsed:
        raise HTTPException(status_code=400, detail="At least one symbol is required")
    results = await asyncio.gather(*(_best_crypto_quote(s) for s in parsed))
    return [r for r in results if r is not None]


@router.get("/{symbol}", response_model=CryptoQuote)
async def get_crypto(symbol: str) -> CryptoQuote:
    q = await _best_crypto_quote(symbol)
    if q is None:
        raise HTTPException(status_code=502, detail=f"crypto provider error for {symbol}")
    return q
