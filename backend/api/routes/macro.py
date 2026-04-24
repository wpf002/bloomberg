from typing import List

from fastapi import APIRouter, HTTPException, Query

from ...data.sources import FredSource
from ...data.sources.fred_source import DEFAULT_SERIES_METADATA
from ...models.schemas import MacroSeries

router = APIRouter()
_fred = FredSource()


@router.get("/series", response_model=List[str])
async def list_series() -> List[str]:
    return list(DEFAULT_SERIES_METADATA.keys())


@router.get("/series/{series_id}", response_model=MacroSeries)
async def get_series(series_id: str, limit: int = Query(120, ge=1, le=5000)) -> MacroSeries:
    try:
        return await _fred.get_series(series_id.upper(), limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"fred error: {exc}") from exc
