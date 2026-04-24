import logging

from fastapi import APIRouter, HTTPException

from ...data.sources import FmpSource, YFinanceSource
from ...models.schemas import Fundamentals

logger = logging.getLogger(__name__)

router = APIRouter()
_fmp = FmpSource()
_yf = YFinanceSource()


def _is_empty(f: Fundamentals) -> bool:
    """A fundamentals payload is 'empty' if it has no name AND no headline metrics."""
    return not f.name and f.market_cap is None and f.pe_ratio is None and f.revenue_ttm is None


@router.get("/{symbol}", response_model=Fundamentals)
async def get_fundamentals(symbol: str) -> Fundamentals:
    sym = symbol.upper()

    if _fmp.enabled():
        try:
            primary = await _fmp.get_fundamentals(sym)
            if not _is_empty(primary):
                return primary
            logger.info("FMP returned empty for %s, falling back to yfinance", sym)
        except Exception as exc:
            logger.warning("FMP fundamentals failed for %s: %s", sym, exc)

    try:
        return await _yf.get_fundamentals(sym)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"fundamentals provider error: {exc}") from exc
