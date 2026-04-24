from typing import List

from fastapi import APIRouter, HTTPException, Query

from ...data.sources import YFinanceSource
from ...models.schemas import FxQuote

router = APIRouter()
_yf = YFinanceSource()

DEFAULT_PAIRS = ["EURUSD", "GBPUSD", "USDJPY", "USDCHF", "USDCAD", "AUDUSD", "NZDUSD", "USDMXN"]


@router.get("", response_model=List[FxQuote])
async def list_fx(
    pairs: str = Query(",".join(DEFAULT_PAIRS), description="Comma-separated ISO pairs, e.g. EURUSD,USDJPY"),
) -> List[FxQuote]:
    parsed = [p.strip().upper() for p in pairs.split(",") if p.strip()]
    if not parsed:
        raise HTTPException(status_code=400, detail="At least one pair is required")
    try:
        return [await _yf.get_fx_quote(p) for p in parsed]
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"fx provider error: {exc}") from exc


@router.get("/{pair}", response_model=FxQuote)
async def get_pair(pair: str) -> FxQuote:
    try:
        return await _yf.get_fx_quote(pair.upper())
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"fx provider error: {exc}") from exc
