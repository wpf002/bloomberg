"""Portfolio factor analysis — Fama-French 5 + Carhart momentum.

Given a list of `(symbol, weight)` positions, we:
  1. Pull `lookback_days` of daily bars per symbol.
  2. Compute weighted daily portfolio returns under the *current* weights
     (a static-weights regression, the same simplification every retail
     factor tool uses — the user doesn't have a daily holdings history).
  3. Subtract the daily risk-free rate to get excess returns.
  4. Regress excess returns on Mkt-RF, SMB, HML, RMW, CMA, MOM via
     numpy.linalg.lstsq. Returns betas + alpha + R² + window length.

We use OLS without a Newey-West correction. For prosumer reads at the
daily timescale that's accurate enough; if anyone asks for HAC standard
errors we'll bring statsmodels in.
"""

from __future__ import annotations

import logging
from datetime import date as date_cls, datetime
from typing import Any

import numpy as np

from ..data.sources.alpaca_source import get_alpaca_source
from ..data.sources.french_source import FrenchSource
from ..models.schemas import QuoteHistoryPoint

logger = logging.getLogger(__name__)


FACTOR_KEYS = ("mkt_rf", "smb", "hml", "rmw", "cma", "mom")


async def _bars_by_date(symbol: str, lookback_days: int) -> dict[date_cls, float]:
    """Pull daily closes for `symbol`, return date → close. Wrapped so a
    single failed symbol doesn't poison the whole portfolio regression."""
    period = "2y" if lookback_days > 365 else "1y"
    alpaca = get_alpaca_source()
    try:
        bars: list[QuoteHistoryPoint] = await alpaca.get_stock_bars(symbol, period=period, interval="1d")
    except Exception as exc:
        logger.debug("factor bars %s alpaca failed: %s", symbol, exc)
        bars = []
    out: dict[date_cls, float] = {}
    for b in bars:
        try:
            out[b.timestamp.date()] = float(b.close)
        except Exception:
            continue
    return out


def _portfolio_returns(
    closes_by_symbol: dict[str, dict[date_cls, float]],
    weights: dict[str, float],
) -> dict[date_cls, float]:
    """Equal-window daily portfolio return under static `weights`.

    For each date, return = Σ w_i * (close_i_t / close_i_{t-1} - 1).
    A symbol that's missing data for a given day is dropped from that
    day's calculation — we don't want one stale ticker stranding the
    whole panel."""
    # Build a per-symbol sorted (date, close) list for prev-close lookups
    series: dict[str, list[tuple[date_cls, float]]] = {
        sym: sorted(rows.items()) for sym, rows in closes_by_symbol.items() if rows
    }
    daily_return_components: dict[date_cls, list[tuple[float, float]]] = {}
    for sym, points in series.items():
        weight = weights.get(sym, 0.0)
        if weight == 0:
            continue
        for i in range(1, len(points)):
            d, c = points[i]
            _, prev_c = points[i - 1]
            if prev_c <= 0:
                continue
            r = c / prev_c - 1.0
            daily_return_components.setdefault(d, []).append((weight, r))
    out: dict[date_cls, float] = {}
    for d, parts in daily_return_components.items():
        total_weight = sum(w for w, _ in parts)
        if total_weight <= 0:
            continue
        out[d] = sum(w * r for w, r in parts) / total_weight
    return out


def _ols(y: np.ndarray, x: np.ndarray) -> tuple[np.ndarray, float]:
    """Fit y = X*beta + epsilon (with intercept already in x[:,0]). Return
    (beta vector, R²)."""
    beta, *_ = np.linalg.lstsq(x, y, rcond=None)
    y_hat = x @ beta
    ss_res = float(np.sum((y - y_hat) ** 2))
    ss_tot = float(np.sum((y - np.mean(y)) ** 2))
    r2 = 1.0 - (ss_res / ss_tot) if ss_tot > 0 else 0.0
    return beta, r2


async def factor_regression(
    weights: dict[str, float],
    lookback_days: int = 252,
) -> dict[str, Any] | None:
    """Run the 6-factor regression. Returns None when there's not enough
    overlapping data (fewer than 30 paired days)."""
    if not weights:
        return None
    factors = await FrenchSource().load()
    if not factors:
        return None
    factors_by_date: dict[date_cls, dict[str, float]] = {}
    for row in factors:
        try:
            d = datetime.fromisoformat(row["date"]).date()
        except Exception:
            continue
        factors_by_date[d] = {k: row.get(k) for k in (*FACTOR_KEYS, "rf")}

    # Pull bars in parallel
    import asyncio
    closes_by_symbol = dict(
        zip(
            weights.keys(),
            await asyncio.gather(*(_bars_by_date(sym, lookback_days) for sym in weights.keys())),
        )
    )

    port_returns = _portfolio_returns(closes_by_symbol, weights)
    if not port_returns:
        return None

    # Align dates with the factor calendar; trim to the lookback
    common = sorted(set(port_returns.keys()) & set(factors_by_date.keys()))
    if len(common) > lookback_days:
        common = common[-lookback_days:]
    if len(common) < 30:
        logger.debug("factor regression: only %d aligned days, need >=30", len(common))
        return None

    y_list: list[float] = []
    x_list: list[list[float]] = []
    for d in common:
        f = factors_by_date[d]
        rf = f.get("rf") or 0.0
        port_excess = port_returns[d] - rf
        y_list.append(port_excess)
        x_list.append([1.0] + [f[k] for k in FACTOR_KEYS])

    y = np.array(y_list, dtype=float)
    x = np.array(x_list, dtype=float)
    beta, r2 = _ols(y, x)

    # Annualize alpha (intercept) — daily intercept × 252
    alpha_daily = float(beta[0])
    alpha_annual = alpha_daily * 252

    return {
        "alpha_annual": alpha_annual,
        "alpha_daily": alpha_daily,
        "factors": {k: float(v) for k, v in zip(FACTOR_KEYS, beta[1:])},
        "r_squared": float(r2),
        "observations": len(common),
        "first_date": common[0].isoformat(),
        "last_date": common[-1].isoformat(),
    }
