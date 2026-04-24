from typing import List

from fastapi import APIRouter, HTTPException, Query

from ...data.sources import SecEdgarSource
from ...models.schemas import FilingEntry

router = APIRouter()
_edgar = SecEdgarSource()


@router.get("/{symbol}", response_model=List[FilingEntry])
async def get_filings(
    symbol: str,
    forms: str = Query("10-K,10-Q,8-K", description="Comma-separated SEC form types"),
    limit: int = Query(20, ge=1, le=100),
) -> List[FilingEntry]:
    form_types = [f.strip().upper() for f in forms.split(",") if f.strip()]
    try:
        return await _edgar.recent_filings(symbol.upper(), form_types=form_types, limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"edgar error: {exc}") from exc
