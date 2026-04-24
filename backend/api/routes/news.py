from typing import List

from fastapi import APIRouter, HTTPException, Query

from ...data.sources import AlpacaSource
from ...models.schemas import NewsItem

router = APIRouter()
_alpaca = AlpacaSource()


@router.get("", response_model=List[NewsItem])
async def get_news(
    symbols: str | None = Query(None, description="Comma-separated tickers"),
    limit: int = Query(25, ge=1, le=100),
) -> List[NewsItem]:
    parsed = [s.strip().upper() for s in symbols.split(",")] if symbols else None
    try:
        return await _alpaca.news(parsed, limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"news provider error: {exc}") from exc
