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
    except Exception as exc:
        logger.warning("alpaca options failed for %s: %s", sym, exc)
        return OptionChain(symbol=sym)
    # V2.6: feed at-the-money IV into the CBOE rolling buffer so the
    # /api/market/iv endpoint can compute IV rank + percentile.
    try:
        from ...data.sources.cboe_source import get_cboe_source

        spot = chain.underlying_price
        if spot:
            atm_iv = _atm_iv(chain.calls, chain.puts, spot)
            if atm_iv is not None and atm_iv > 0:
                get_cboe_source().record_iv(sym, atm_iv)
    except Exception:
        pass
    return chain


def _atm_iv(calls, puts, spot: float) -> float | None:
    """Mean of the call+put IV at the strike closest to spot."""
    if spot is None or spot <= 0:
        return None
    contracts = list(calls or []) + list(puts or [])
    if not contracts:
        return None
    closest = min(contracts, key=lambda c: abs((c.strike or 0) - spot))
    target_strike = closest.strike
    same_strike = [c for c in contracts if c.strike == target_strike and (c.implied_volatility or 0) > 0]
    if not same_strike:
        return None
    ivs = [c.implied_volatility for c in same_strike if c.implied_volatility]
    return sum(ivs) / len(ivs) if ivs else None
