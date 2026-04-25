import asyncio
from typing import List

from fastapi import APIRouter, HTTPException, Query

from ...data.sources import FinnhubSource, RssSource, get_alpaca_source
from ...models.schemas import NewsItem

router = APIRouter()
_alpaca = get_alpaca_source()
_finnhub = FinnhubSource()
_rss = RssSource()


@router.get("", response_model=List[NewsItem])
async def get_news(
    symbols: str | None = Query(None, description="Comma-separated tickers"),
    limit: int = Query(30, ge=1, le=100),
) -> List[NewsItem]:
    """Multi-source news merge: Alpaca news (primary), Finnhub
    company-news (per-symbol when symbols are passed), and remaining
    RSS feeds (MarketWatch, Nasdaq, SEC). Yahoo RSS retired.
    """
    parsed = [s.strip().upper() for s in symbols.split(",") if s.strip()] if symbols else None

    async def _safe(coro, default):
        try:
            return await coro
        except Exception:
            return default

    finnhub_tasks = []
    if parsed:
        finnhub_tasks = [_safe(_finnhub.get_company_news(sym, limit=limit), []) for sym in parsed]

    try:
        alpaca_items, rss_items, *finnhub_results = await asyncio.gather(
            _safe(_alpaca.news(parsed, limit=limit), []),
            _safe(_rss.fetch(parsed, limit=limit), []),
            *finnhub_tasks,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"news error: {exc}") from exc

    merged: List[NewsItem] = []
    seen: set[str] = set()
    sources = [alpaca_items, rss_items, *finnhub_results]
    for source in sources:
        if not source:
            continue
        for item in source:
            key = item.url or item.id
            if key in seen:
                continue
            seen.add(key)
            merged.append(item)

    merged.sort(key=lambda n: n.published_at, reverse=True)
    return merged[:limit]
