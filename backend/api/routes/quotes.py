from typing import List

from fastapi import APIRouter, HTTPException, Query

from ...data.sources import YFinanceSource
from ...models.schemas import Quote, QuoteHistoryPoint

router = APIRouter()
_yf = YFinanceSource()


@router.get("", response_model=List[Quote])
async def get_quotes(symbols: str = Query(..., description="Comma-separated ticker list")) -> List[Quote]:
    parsed = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    if not parsed:
        raise HTTPException(status_code=400, detail="At least one symbol is required")
    try:
        return await _yf.get_quotes(parsed)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"quote provider error: {exc}") from exc


@router.get("/{symbol}", response_model=Quote)
async def get_quote(symbol: str) -> Quote:
    try:
        return await _yf.get_quote(symbol.upper())
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"quote provider error: {exc}") from exc


@router.get("/{symbol}/history", response_model=List[QuoteHistoryPoint])
async def get_history(
    symbol: str,
    period: str = Query("1mo", description="e.g. 1d, 5d, 1mo, 3mo, 6mo, 1y, 5y, max"),
    interval: str = Query("1d", description="e.g. 1m, 5m, 15m, 1h, 1d, 1wk"),
) -> List[QuoteHistoryPoint]:
    try:
        return await _yf.get_history(symbol.upper(), period=period, interval=interval)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"history provider error: {exc}") from exc
