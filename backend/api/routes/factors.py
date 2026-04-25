"""Portfolio factor analysis — Fama-French 5 + Carhart momentum.

Bloomberg's `MARS` panel, but free, run against your live Alpaca paper
positions. We compute current value-weights from the broker, regress
hypothetical static-weight returns over the lookback against the factors,
and return the betas + alpha + R².

Static weights are the standard simplification — daily holdings history
isn't a thing on Alpaca paper, and most retail factor tools work this way.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query

from ...core.factor_analysis import factor_regression
from ...data.sources import get_alpaca_source
from ...models.schemas import FactorReport

logger = logging.getLogger(__name__)
router = APIRouter()
_alpaca = get_alpaca_source()


@router.get("/factors", response_model=FactorReport)
async def portfolio_factors(
    lookback_days: int = Query(252, ge=30, le=1260),
) -> FactorReport:
    """6-factor regression on the current Alpaca paper portfolio."""
    if not _alpaca.credentials_configured():
        raise HTTPException(
            status_code=503,
            detail="alpaca credentials missing — add ALPACA_API_KEY/SECRET",
        )
    positions = await _alpaca.get_positions()
    if not positions:
        return FactorReport(
            alpha_annual=0.0,
            alpha_daily=0.0,
            factors={},
            r_squared=0.0,
            observations=0,
            first_date="",
            last_date="",
            weights={},
            insufficient_data=True,
            message="no open positions to analyze",
        )

    weights: dict[str, float] = {}
    total_value = 0.0
    for pos in positions:
        mv = float(pos.market_value or 0.0)
        if mv > 0:
            weights[pos.symbol.upper()] = mv
            total_value += mv
    if total_value <= 0:
        return FactorReport(
            alpha_annual=0.0,
            alpha_daily=0.0,
            factors={},
            r_squared=0.0,
            observations=0,
            first_date="",
            last_date="",
            weights={},
            insufficient_data=True,
            message="position market values are zero",
        )
    weights = {sym: mv / total_value for sym, mv in weights.items()}

    try:
        result = await factor_regression(weights, lookback_days=lookback_days)
    except Exception as exc:
        logger.exception("factor regression failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"factor regression error: {exc}") from exc

    if result is None:
        return FactorReport(
            alpha_annual=0.0,
            alpha_daily=0.0,
            factors={},
            r_squared=0.0,
            observations=0,
            first_date="",
            last_date="",
            weights=weights,
            insufficient_data=True,
            message="not enough overlapping data — need ≥30 trading days of bars + factors",
        )

    return FactorReport(
        alpha_annual=result["alpha_annual"],
        alpha_daily=result["alpha_daily"],
        factors=result["factors"],
        r_squared=result["r_squared"],
        observations=result["observations"],
        first_date=result["first_date"],
        last_date=result["last_date"],
        weights=weights,
        insufficient_data=result["observations"] < 90,
        message=(
            f"only {result['observations']} aligned days — wide confidence intervals"
            if result["observations"] < 90
            else None
        ),
    )
