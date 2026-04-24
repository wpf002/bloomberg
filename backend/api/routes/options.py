import logging

from fastapi import APIRouter, Query

from ...data.sources import YFinanceSource
from ...models.schemas import OptionChain

logger = logging.getLogger(__name__)
router = APIRouter()
_yf = YFinanceSource()


@router.get("/{symbol}", response_model=OptionChain)
async def get_chain(
    symbol: str,
    expiration: str | None = Query(None, description="YYYY-MM-DD; defaults to the nearest expiration"),
) -> OptionChain:
    sym = symbol.upper()
    try:
        return await _yf.get_option_chain(sym, expiration=expiration)
    except Exception as exc:
        # yfinance scrapes Yahoo; transient 429s and JSON-decode errors are
        # expected. Return an empty chain so the UI can render a "no data"
        # state instead of a scary 502.
        logger.warning("options provider failed for %s: %s", sym, exc)
        return OptionChain(symbol=sym)
