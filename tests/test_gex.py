"""V2.4 — GEX/VEX computation math.

Validates the per-strike aggregation, net GEX sign convention,
flip-point interpolation, and vanna fallback for the VEX profile.
We don't hit Alpaca — synthetic OptionContract dicts feed the math
directly so tests are deterministic.
"""

from __future__ import annotations

import math
from types import SimpleNamespace

from backend.services.risk_engine import (
    _bsm_vanna,
    _gex_flip_point,
    compute_gex_profile,
    compute_vex_profile,
)


def _opt(option_type, strike, oi, gamma=None, iv=0.0, expiration="2026-12-19"):
    return SimpleNamespace(
        option_type=option_type,
        strike=float(strike),
        open_interest=int(oi),
        gamma=gamma,
        implied_volatility=iv,
        expiration=expiration,
    )


def test_gex_zero_when_chain_empty():
    p = compute_gex_profile(spot=100.0, contracts=[])
    assert p["net_gex"] == 0.0
    assert p["strikes"] == []
    assert p["flip_point"] is None


def test_gex_calls_positive_puts_negative():
    spot = 100.0
    contracts = [
        _opt("call", 100, oi=1000, gamma=0.05),
        _opt("put",  100, oi=1000, gamma=0.05),
    ]
    p = compute_gex_profile(spot=spot, contracts=contracts)
    rows = p["strikes"]
    assert len(rows) == 1
    row = rows[0]
    # OI * gamma * 100 * spot^2 * 0.01
    expected = 1000 * 0.05 * 100 * (spot * spot) * 0.01
    assert math.isclose(row["call_gex"], expected, rel_tol=1e-9)
    assert math.isclose(row["put_gex"], -expected, rel_tol=1e-9)
    assert math.isclose(row["net_gex"], 0.0, abs_tol=1e-6)


def test_gex_max_gamma_strike_picks_largest_abs():
    spot = 100.0
    contracts = [
        _opt("call", 95,  oi=500,  gamma=0.04),
        _opt("call", 100, oi=2000, gamma=0.06),
        _opt("call", 105, oi=300,  gamma=0.03),
    ]
    p = compute_gex_profile(spot=spot, contracts=contracts)
    assert p["max_gamma_strike"] == 100
    assert p["walls"][0]["strike"] == 100
    assert all(w["gex"] != 0 for w in p["walls"])


def test_gex_flip_point_interpolation():
    rows = [
        {"strike": 90.0,  "call_gex": 0.0, "put_gex": -100.0, "net_gex": -100.0},
        {"strike": 100.0, "call_gex": 0.0, "put_gex":  -50.0, "net_gex":  -50.0},
        {"strike": 110.0, "call_gex": 200.0,"put_gex":  0.0,  "net_gex":  200.0},
    ]
    flip = _gex_flip_point(rows)
    # cumulative net: -100, -150, +50. Crosses zero between 100 and 110.
    assert flip is not None
    assert 100.0 <= flip <= 110.0


def test_gex_flip_point_returns_none_with_one_sided_book():
    rows = [
        {"strike": 90.0,  "net_gex": -100.0, "call_gex": 0.0, "put_gex": -100.0},
        {"strike": 100.0, "net_gex": -200.0, "call_gex": 0.0, "put_gex": -200.0},
    ]
    assert _gex_flip_point(rows) is None


def test_bsm_vanna_signs_when_otm_call():
    # Spot below strike: d1 < 0 → vanna > 0 (because vanna = -d1 * pdf / ...)
    v = _bsm_vanna(spot=90.0, strike=100.0, t_years=0.25, rate=0.04, sigma=0.30)
    assert v > 0


def test_bsm_vanna_zero_for_degenerate_input():
    assert _bsm_vanna(0.0, 100.0, 0.25, 0.04, 0.30) == 0.0
    assert _bsm_vanna(100.0, 100.0, 0.0, 0.04, 0.30) == 0.0
    assert _bsm_vanna(100.0, 100.0, 0.25, 0.04, 0.0) == 0.0


def test_vex_profile_uses_iv_fallback_when_vanna_missing():
    spot = 100.0
    contracts = [
        _opt("call", 90, oi=500, iv=0.30),
        _opt("call", 110, oi=500, iv=0.30),
        _opt("put",  90, oi=500, iv=0.30),
        _opt("put",  110, oi=500, iv=0.30),
    ]
    p = compute_vex_profile(spot=spot, contracts=contracts)
    assert len(p["strikes"]) == 2
    assert p["spot"] == spot
    # net_vex must be a finite number even when chain has no vanna field
    assert math.isfinite(p["net_vex"])


def test_vex_returns_empty_when_spot_invalid():
    p = compute_vex_profile(spot=0.0, contracts=[_opt("call", 100, oi=100, iv=0.3)])
    assert p["strikes"] == []
    assert p["net_vex"] == 0.0
