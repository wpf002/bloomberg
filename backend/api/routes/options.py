from fastapi import APIRouter, HTTPException, Query

from ...data.sources import YFinanceSource
from ...models.schemas import OptionChain

router = APIRouter()
_yf = YFinanceSource()


@router.get("/{symbol}", response_model=OptionChain)
async def get_chain(
    symbol: str,
    expiration: str | None = Query(None, description="YYYY-MM-DD; defaults to the nearest expiration"),
) -> OptionChain:
    try:
        return await _yf.get_option_chain(symbol.upper(), expiration=expiration)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"options provider error: {exc}") from exc
