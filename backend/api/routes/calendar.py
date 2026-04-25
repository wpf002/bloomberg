import asyncio
from datetime import date, timedelta
from typing import List

from fastapi import APIRouter, HTTPException, Query

from ...data.sources import FinnhubSource
from ...models.schemas import EarningsEvent

router = APIRouter()
_finnhub = FinnhubSource()


@router.get("/earnings", response_model=List[EarningsEvent])
async def earnings_calendar(
    symbols: str = Query(..., description="Comma-separated tickers, e.g. AAPL,MSFT,NVDA"),
    limit: int = Query(8, ge=1, le=20),
    upcoming_only: bool = Query(True, description="Drop events whose date is more than 1 day in the past"),
) -> List[EarningsEvent]:
    """Earnings calendar via Finnhub. We fan out one request per symbol
    (free tier is 60 req/min and the cache absorbs reloads) because the
    market-wide endpoint silently caps at ~1500 events and small/large
    caps both get dropped. yfinance fallback retired with the rest of
    the Yahoo deps; if Finnhub isn't configured the panel renders empty."""
    parsed = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    if not parsed:
        raise HTTPException(status_code=400, detail="At least one symbol is required")
    if not _finnhub.enabled():
        return []

    cutoff = date.today() - timedelta(days=1)
    from_date = date.today() if upcoming_only else cutoff
    horizon_end = date.today() + timedelta(days=120)

    results = await asyncio.gather(
        *(
            _finnhub.get_earnings_calendar(
                symbol=sym, from_date=from_date, to_date=horizon_end
            )
            for sym in parsed
        ),
        return_exceptions=True,
    )
    merged: List[EarningsEvent] = []
    for result in results:
        if isinstance(result, Exception) or not result:
            continue
        merged.extend(result)
    return _trim_per_symbol(merged, limit)


def _trim_per_symbol(events: List[EarningsEvent], per_symbol: int) -> List[EarningsEvent]:
    """Keep up to `per_symbol` upcoming dates per ticker, sorted by date."""
    seen: dict[str, int] = {}
    kept: List[EarningsEvent] = []
    for event in sorted(events, key=lambda e: e.event_date):
        count = seen.get(event.symbol, 0)
        if count >= per_symbol:
            continue
        kept.append(event)
        seen[event.symbol] = count + 1
    kept.sort(key=lambda e: e.event_date)
    return kept
