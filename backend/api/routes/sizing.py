"""Position-sizing calculator.

Given an account equity (pulled live from Alpaca), current price, and a
stop-loss distance the user is willing to accept, compute how many shares
to buy at a grid of account-risk levels (0.5%, 1%, 2%, 5% of equity).

This is the "never risk more than N% of equity on a single trade" rule
every pro-facing platform ships in some form; Bloomberg's PORT / MARS have
richer versions. Math is deterministic; no provider dependency besides a
price and an equity value.
"""

from __future__ import annotations

import logging
import math

from fastapi import APIRouter, HTTPException, Query

from ...data.sources import FinnhubSource, get_alpaca_source
from ...models.schemas import PositionSize, SizingRow

logger = logging.getLogger(__name__)
router = APIRouter()
_alpaca = get_alpaca_source()
_finnhub = FinnhubSource()

RISK_GRID = (0.5, 1.0, 2.0, 5.0)


async def _price(symbol: str) -> float | None:
    """Alpaca snapshot first, Finnhub fallback for indices Alpaca doesn't carry."""
    try:
        q = await _alpaca.get_stock_quote(symbol)
        if q and q.price > 0:
            return q.price
    except Exception as exc:
        logger.warning("alpaca snapshot failed for %s: %s", symbol, exc)
    try:
        q = await _finnhub.get_quote(symbol)
        if q and q.price > 0:
            return q.price
    except Exception as exc:
        logger.warning("finnhub quote failed for %s: %s", symbol, exc)
    return None


@router.get("/{symbol}", response_model=PositionSize)
async def get_sizing(
    symbol: str,
    stop_pct: float = Query(
        5.0,
        gt=0.0,
        le=50.0,
        description="Stop-loss distance from entry, as a percent (e.g. 5 = 5% stop)",
    ),
) -> PositionSize:
    sym = symbol.upper()
    if not _alpaca.credentials_configured():
        raise HTTPException(
            status_code=503,
            detail=(
                "Alpaca credentials not configured. Sizing needs live equity; "
                "add ALPACA_API_KEY + ALPACA_API_SECRET to .env and restart."
            ),
        )
    account = await _alpaca.get_account()
    if account is None or account.equity <= 0:
        raise HTTPException(status_code=502, detail="Alpaca account fetch failed")

    price = await _price(sym)
    if price is None or price <= 0:
        raise HTTPException(status_code=502, detail=f"No price available for {sym}")

    risk_per_share = price * (stop_pct / 100.0)
    rows: list[SizingRow] = []
    for risk_pct in RISK_GRID:
        max_loss = account.equity * (risk_pct / 100.0)
        shares = int(math.floor(max_loss / risk_per_share)) if risk_per_share > 0 else 0
        notional = shares * price
        rows.append(
            SizingRow(
                risk_pct=risk_pct,
                max_loss_usd=max_loss,
                shares=shares,
                notional_usd=notional,
                notional_pct=(notional / account.equity * 100.0) if account.equity else 0.0,
            )
        )

    return PositionSize(
        symbol=sym,
        price=price,
        equity=account.equity,
        stop_pct=stop_pct,
        rows=rows,
        source=account.source,
    )
