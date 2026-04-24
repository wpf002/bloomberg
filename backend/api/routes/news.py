import asyncio
from typing import List

from fastapi import APIRouter, HTTPException, Query

from ...data.sources import AlpacaSource, RssSource
from ...models.schemas import NewsItem

router = APIRouter()
_alpaca = AlpacaSource()
_rss = RssSource()


@router.get("", response_model=List[NewsItem])
async def get_news(
    symbols: str | None = Query(None, description="Comma-separated tickers"),
    limit: int = Query(30, ge=1, le=100),
) -> List[NewsItem]:
    parsed = [s.strip().upper() for s in symbols.split(",") if s.strip()] if symbols else None
    try:
        alpaca_task = _alpaca.news(parsed, limit=limit)
        rss_task = _rss.fetch(parsed, limit=limit)
        alpaca_items, rss_items = await asyncio.gather(
            alpaca_task, rss_task, return_exceptions=True
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"news error: {exc}") from exc

    merged: List[NewsItem] = []
    seen: set[str] = set()
    for source in (alpaca_items, rss_items):
        if isinstance(source, Exception) or not source:
            continue
        for item in source:
            key = item.url or item.id
            if key in seen:
                continue
            seen.add(key)
            merged.append(item)

    merged.sort(key=lambda n: n.published_at, reverse=True)
    return merged[:limit]
