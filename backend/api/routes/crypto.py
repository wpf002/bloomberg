from typing import List

from fastapi import APIRouter, HTTPException, Query

from ...data.sources import YFinanceSource
from ...models.schemas import CryptoQuote

router = APIRouter()
_yf = YFinanceSource()

DEFAULT_SYMBOLS = ["BTC-USD", "ETH-USD", "SOL-USD", "XRP-USD", "ADA-USD"]


@router.get("", response_model=List[CryptoQuote])
async def list_crypto(
    symbols: str = Query(
        ",".join(DEFAULT_SYMBOLS),
        description="Comma-separated crypto pair tickers (yfinance style, e.g. BTC-USD)",
    ),
) -> List[CryptoQuote]:
    parsed = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    if not parsed:
        raise HTTPException(status_code=400, detail="At least one symbol is required")
    try:
        return [await _yf.get_crypto_quote(sym) for sym in parsed]
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"crypto provider error: {exc}") from exc


@router.get("/{symbol}", response_model=CryptoQuote)
async def get_crypto(symbol: str) -> CryptoQuote:
    try:
        return await _yf.get_crypto_quote(symbol.upper())
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"crypto provider error: {exc}") from exc
