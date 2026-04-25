import asyncio
import logging
from typing import List

from fastapi import APIRouter, HTTPException, Query

from ...data.sources import get_alpaca_source
from ...models.schemas import CryptoQuote

logger = logging.getLogger(__name__)
router = APIRouter()
_alpaca = get_alpaca_source()

DEFAULT_SYMBOLS = ["BTC-USD", "ETH-USD", "SOL-USD", "XRP-USD", "ADA-USD"]


async def _best_crypto_quote(symbol: str) -> CryptoQuote | None:
    """Alpaca crypto snapshot. yfinance fallback retired — Alpaca covers
    all the major pairs reliably and is the same data path we use for
    equities so coverage and rate limits are predictable."""
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
        raise HTTPException(status_code=404, detail=f"alpaca doesn't carry {symbol}")
    return q
