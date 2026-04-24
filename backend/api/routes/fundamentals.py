from fastapi import APIRouter, HTTPException

from ...data.sources import YFinanceSource
from ...models.schemas import Fundamentals

router = APIRouter()
_yf = YFinanceSource()


@router.get("/{symbol}", response_model=Fundamentals)
async def get_fundamentals(symbol: str) -> Fundamentals:
    try:
        return await _yf.get_fundamentals(symbol.upper())
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"fundamentals provider error: {exc}") from exc
