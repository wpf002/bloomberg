"""Options payoff math at expiration.

For a multi-leg strategy (calls + puts + stock) we compute the per-leg
intrinsic value at each candidate underlying price, sum across legs, and
report the payoff curve, breakevens, and bounded max-profit / max-loss
where they exist.

Pricing model: payoff at expiry only — no time value, no greeks. This is
the line every options textbook draws and the one retail traders look at.
For mid-trade marks use BSM (already in `core/bsm.py`).
"""

from __future__ import annotations

from typing import List, Optional

from ..models.schemas import PayoffCurve, PayoffLeg, PayoffPoint

DEFAULT_POINTS = 121
SPOT_PADDING = 0.4  # ±40% of underlying covers nearly every retail strategy


def _leg_value_at(leg: PayoffLeg, spot: float, multiplier: int) -> float:
    """Return the P/L of one leg at a given spot at expiry."""
    qty = leg.qty * (1 if leg.side == "long" else -1)
    if leg.type == "stock":
        return (spot - leg.premium) * qty  # qty here is shares, multiplier=1
    if leg.type == "call":
        intrinsic = max(spot - leg.strike, 0.0)
    elif leg.type == "put":
        intrinsic = max(leg.strike - spot, 0.0)
    else:
        intrinsic = 0.0
    return (intrinsic - leg.premium) * qty * multiplier


def _net_premium(legs: List[PayoffLeg], multiplier: int) -> float:
    """Positive = credit, Negative = debit. Stock legs are excluded — they
    aren't a premium, they're a cost basis."""
    total = 0.0
    for leg in legs:
        if leg.type == "stock":
            continue
        sign = 1 if leg.side == "short" else -1  # short = receive premium
        total += sign * leg.premium * leg.qty * multiplier
    return total


def _find_breakevens(points: List[PayoffPoint]) -> List[float]:
    """Linear-interpolate zero crossings between adjacent payoff points."""
    out: List[float] = []
    for i in range(1, len(points)):
        a, b = points[i - 1], points[i]
        if a.pnl == 0:
            out.append(round(a.spot, 4))
        if (a.pnl < 0 and b.pnl > 0) or (a.pnl > 0 and b.pnl < 0):
            ratio = a.pnl / (a.pnl - b.pnl)
            out.append(round(a.spot + ratio * (b.spot - a.spot), 4))
    if points and points[-1].pnl == 0 and (not out or out[-1] != points[-1].spot):
        out.append(round(points[-1].spot, 4))
    # Dedupe adjacent floats within rounding noise.
    cleaned: List[float] = []
    for v in out:
        if not cleaned or abs(v - cleaned[-1]) > 1e-3:
            cleaned.append(v)
    return cleaned


def _bounded_extrema(points: List[PayoffPoint]) -> tuple[Optional[float], Optional[float]]:
    """A strategy with monotonic edges has unbounded P/L on that side. We
    detect that by checking whether the slope keeps changing past the last
    sampled point: if the final two points already trend together, treat
    that side as unbounded."""
    if len(points) < 3:
        return (None, None)
    pnls = [p.pnl for p in points]
    left_unbounded_up = pnls[1] > pnls[0]
    left_unbounded_down = pnls[1] < pnls[0]
    right_unbounded_up = pnls[-1] > pnls[-2]
    right_unbounded_down = pnls[-1] < pnls[-2]

    max_profit = max(pnls)
    max_loss = min(pnls)
    if left_unbounded_up or right_unbounded_up:
        max_profit = None  # unbounded upside
    if left_unbounded_down or right_unbounded_down:
        max_loss = None  # unbounded downside
    return (max_profit, max_loss)


def build_payoff(
    underlying_price: float,
    legs: List[PayoffLeg],
    *,
    multiplier: int = 100,
    points: int = DEFAULT_POINTS,
    padding: float = SPOT_PADDING,
) -> PayoffCurve:
    if not legs:
        return PayoffCurve(
            underlying_price=underlying_price,
            legs=[],
            points=[],
        )

    low = max(0.01, underlying_price * (1 - padding))
    high = underlying_price * (1 + padding)
    # Make sure each strike is included so kinks land exactly on data points.
    strikes = sorted({leg.strike for leg in legs if leg.type in {"call", "put"} and leg.strike > 0})
    grid: list[float] = []
    n = max(11, points)
    step = (high - low) / (n - 1)
    for i in range(n):
        grid.append(low + i * step)
    grid.extend(strikes)
    grid = sorted(set(round(v, 4) for v in grid if v > 0))

    pts: List[PayoffPoint] = []
    for spot in grid:
        pnl = sum(_leg_value_at(leg, spot, multiplier) for leg in legs)
        pts.append(PayoffPoint(spot=spot, pnl=pnl))

    breakevens = _find_breakevens(pts)
    max_profit, max_loss = _bounded_extrema(pts)
    net_prem = _net_premium(legs, multiplier)

    return PayoffCurve(
        underlying_price=underlying_price,
        legs=legs,
        points=pts,
        breakevens=breakevens,
        max_profit=max_profit,
        max_loss=max_loss,
        net_premium=net_prem,
        contract_multiplier=multiplier,
    )
