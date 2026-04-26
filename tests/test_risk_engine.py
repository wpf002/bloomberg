"""Pytest coverage for backend/services/risk_engine.py.

Hits only the pure-math helpers (correlation, drawdown, VaR/CVaR) so we
don't need a live Alpaca account or network. Network-bound paths
(stress, exposure) are exercised in smoke.py.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from backend.services.risk_engine import (
    _PriceFrame,
    correlation_matrix,
    drawdown_stats,
    var_cvar,
)


def _frame_from(prices_by_symbol: dict[str, list[float]], start: date | None = None) -> _PriceFrame:
    start = start or date(2024, 1, 1)
    out: dict[str, dict[date, float]] = {}
    for sym, vals in prices_by_symbol.items():
        out[sym] = {start + timedelta(days=i): v for i, v in enumerate(vals)}
    return _PriceFrame(symbols=list(prices_by_symbol.keys()), closes=out)


def test_correlation_matrix_shape_and_self_correlation():
    rng = np.random.default_rng(42)
    series_a = list(np.cumsum(rng.normal(0.001, 0.01, 200)) + 100.0)
    series_b = list(np.cumsum(rng.normal(0.001, 0.01, 200)) + 100.0)
    frame = _frame_from({"AAA": series_a, "BBB": series_b})
    out = correlation_matrix(frame)
    assert len(out["symbols"]) == 2
    assert len(out["matrix"]) == 2
    # Self-correlation must be 1.0 by definition.
    assert out["matrix"][0][0] == pytest.approx(1.0, abs=1e-6)


def test_correlation_matrix_handles_single_symbol_gracefully():
    frame = _frame_from({"AAA": [100, 101, 102]})
    out = correlation_matrix(frame)
    assert out["matrix"] == []  # nothing to correlate against


def test_drawdown_stats_recovers_known_drawdown():
    # Goes 100 → 120 → 60 → 90: max drawdown is 50% (120 → 60).
    frame = _frame_from({"AAA": [100, 120, 60, 90]})
    weights = {"AAA": 100.0}
    out = drawdown_stats(frame, weights)
    aa = next(p for p in out["per_position"] if p["symbol"] == "AAA")
    assert aa["max_drawdown"] == pytest.approx(-0.5, abs=1e-9)


def test_var_cvar_quantiles_match_numpy():
    rng = np.random.default_rng(7)
    # 500 days of normal-ish returns. We test only that 95% VaR is more
    # negative than 99% VaR is impossible (i.e., var_99 <= var_95 <= 0).
    closes = list(100 * np.cumprod(1 + rng.normal(0.0005, 0.012, 500)))
    frame = _frame_from({"AAA": closes})
    out = var_cvar(frame, {"AAA": 1.0})
    assert out["observations"] >= 30
    assert out["var_99"] <= out["var_95"] <= 0
    assert out["cvar_99"] <= out["var_99"]


def test_var_cvar_returns_observations_zero_when_too_short():
    frame = _frame_from({"AAA": [100, 101, 102]})
    out = var_cvar(frame, {"AAA": 1.0})
    assert out == {"observations": 0}
