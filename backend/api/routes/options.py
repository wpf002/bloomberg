import logging
from typing import List

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ...core.payoff import build_payoff
from ...data.sources import FinnhubSource, get_alpaca_source
from ...models.schemas import OptionChain, PayoffCurve, PayoffLeg

logger = logging.getLogger(__name__)
router = APIRouter()
_alpaca = get_alpaca_source()
_finnhub = FinnhubSource()


class PayoffRequest(BaseModel):
    symbol: str
    legs: List[PayoffLeg] = Field(default_factory=list)
    underlying_price: float | None = None
    contract_multiplier: int = 100
    points: int = 121
    padding: float = 0.4


@router.post("/payoff", response_model=PayoffCurve)
async def options_payoff(req: PayoffRequest) -> PayoffCurve:
    """Compute a multi-leg expiration payoff curve.

    `underlying_price` is optional — if omitted, we fetch a snapshot.
    """
    if not req.legs:
        raise HTTPException(status_code=400, detail="at least one leg is required")
    spot = req.underlying_price
    if spot is None:
        try:
            quote = await _alpaca.get_stock_quote(req.symbol)
            if quote is None:
                fh = await _finnhub.get_quote(req.symbol)
                quote = fh
            spot = quote.price if quote else None
        except Exception as exc:
            logger.warning("payoff price fetch failed for %s: %s", req.symbol, exc)
            spot = None
    if spot is None or spot <= 0:
        raise HTTPException(status_code=400, detail="provide underlying_price; spot lookup failed")
    return build_payoff(
        underlying_price=spot,
        legs=req.legs,
        multiplier=req.contract_multiplier,
        points=req.points,
        padding=req.padding,
    )


@router.get("/{symbol}", response_model=OptionChain)
async def get_chain(
    symbol: str,
    expiration: str | None = Query(None, description="YYYY-MM-DD; defaults to the nearest expiration"),
) -> OptionChain:
    """Option chain for `symbol`. Alpaca is the only source — they cover
    every US-listed equity + ETF with options. Index options like ^SPX
    require an OPRA-licensed feed we don't carry, and we return an empty
    chain rather than scraping an unreliable fallback."""
    sym = symbol.upper()
    try:
        chain = await _alpaca.get_option_chain(sym, expiration=expiration)
        return chain
    except Exception as exc:
        logger.warning("alpaca options failed for %s: %s", sym, exc)
        return OptionChain(symbol=sym)
