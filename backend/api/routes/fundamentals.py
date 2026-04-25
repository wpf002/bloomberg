import logging

from fastapi import APIRouter, HTTPException

from ...data.sources import FmpSource
from ...models.schemas import Fundamentals

logger = logging.getLogger(__name__)

router = APIRouter()
_fmp = FmpSource()


@router.get("/{symbol}", response_model=Fundamentals)
async def get_fundamentals(symbol: str) -> Fundamentals:
    """FMP is the only source. The Yahoo-via-yfinance fallback we used to
    keep around was slower, blocked under load, and overlapped FMP coverage
    everywhere we cared about. When FMP isn't configured the caller gets
    a sparse `Fundamentals` row (no error) so downstream UI degrades
    gracefully."""
    sym = symbol.upper()
    if not _fmp.enabled():
        return Fundamentals(symbol=sym)
    try:
        return await _fmp.get_fundamentals(sym)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"FMP fundamentals error: {exc}") from exc
