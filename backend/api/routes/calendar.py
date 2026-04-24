import asyncio
from typing import List

from fastapi import APIRouter, HTTPException, Query

from ...data.sources import YFinanceSource
from ...models.schemas import EarningsEvent

router = APIRouter()
_yf = YFinanceSource()


@router.get("/earnings", response_model=List[EarningsEvent])
async def earnings_calendar(
    symbols: str = Query(..., description="Comma-separated tickers, e.g. AAPL,MSFT,NVDA"),
    limit: int = Query(8, ge=1, le=20),
) -> List[EarningsEvent]:
    parsed = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    if not parsed:
        raise HTTPException(status_code=400, detail="At least one symbol is required")
    try:
        results = await asyncio.gather(
            *(_yf.get_upcoming_earnings(sym, limit=limit) for sym in parsed),
            return_exceptions=True,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"earnings provider error: {exc}") from exc

    merged: List[EarningsEvent] = []
    for result in results:
        if isinstance(result, Exception) or not result:
            continue
        merged.extend(result)
    merged.sort(key=lambda e: e.event_date)
    return merged
