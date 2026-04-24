"""Black-Scholes-Merton pricing + Greeks, stdlib-only.

Used to decorate option chain rows with delta/gamma/vega/theta/rho when the
upstream provider only gives price + implied volatility. Good enough for a
retail-facing terminal; for market-making accuracy, swap to py_vollib.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, timezone

SECONDS_PER_YEAR = 365.25 * 24 * 3600


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


@dataclass
class Greeks:
    delta: float
    gamma: float
    vega: float
    theta: float
    rho: float


def year_fraction(expiration: str | date) -> float:
    """Compute T in years from now to an ISO expiration date (UTC end-of-day)."""
    if isinstance(expiration, str):
        exp = datetime.fromisoformat(expiration).replace(tzinfo=timezone.utc)
    else:
        exp = datetime(expiration.year, expiration.month, expiration.day, 20, 0, tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    delta = (exp - now).total_seconds()
    if delta <= 0:
        return 1.0 / 365.25  # floor to one day for expired contracts
    return delta / SECONDS_PER_YEAR


def bsm_greeks(
    spot: float,
    strike: float,
    t_years: float,
    rate: float,
    sigma: float,
    is_call: bool,
) -> Greeks:
    """Return analytical BSM Greeks. Falls back to zeros on degenerate input."""
    if spot <= 0 or strike <= 0 or t_years <= 0 or sigma <= 0:
        return Greeks(0.0, 0.0, 0.0, 0.0, 0.0)

    sqrt_t = math.sqrt(t_years)
    d1 = (math.log(spot / strike) + (rate + 0.5 * sigma * sigma) * t_years) / (sigma * sqrt_t)
    d2 = d1 - sigma * sqrt_t

    pdf_d1 = _norm_pdf(d1)
    cdf_d1 = _norm_cdf(d1)
    cdf_d2 = _norm_cdf(d2)
    disc = math.exp(-rate * t_years)

    if is_call:
        delta = cdf_d1
        theta = (-spot * pdf_d1 * sigma / (2.0 * sqrt_t) - rate * strike * disc * cdf_d2)
        rho = strike * t_years * disc * cdf_d2
    else:
        delta = cdf_d1 - 1.0
        theta = (-spot * pdf_d1 * sigma / (2.0 * sqrt_t) + rate * strike * disc * _norm_cdf(-d2))
        rho = -strike * t_years * disc * _norm_cdf(-d2)

    gamma = pdf_d1 / (spot * sigma * sqrt_t)
    vega = spot * pdf_d1 * sqrt_t

    return Greeks(
        delta=delta,
        gamma=gamma,
        vega=vega / 100.0,   # per 1 vol point
        theta=theta / 365.25, # per calendar day
        rho=rho / 100.0,      # per 1 rate point
    )
