"""Pytest coverage for backend/services/intelligence_engine.py.

Targets the pure-classification logic (regime rules, cycle-phase mapping)
so we don't need FRED or Alpaca network access.
"""

from __future__ import annotations

import pytest

from backend.services.intelligence_engine import RegimeFactors, _cycle_phase, classify_regime


def test_regime_risk_on_when_calm_and_curve_steep():
    r = RegimeFactors(vix=14.0, yield_curve=1.2, spy_30d_return=0.04, cpi_mom_pct=0.2, m2_yoy_pct=2.0)
    regime, conf, factors = classify_regime(r)
    assert regime == "RISK_ON"
    assert 0 <= conf <= 1
    assert any("VIX" in f for f in factors)


def test_regime_risk_off_when_vix_high_and_equities_falling():
    r = RegimeFactors(vix=32.0, yield_curve=-0.3, spy_30d_return=-0.05, cpi_mom_pct=0.3)
    regime, _, _ = classify_regime(r)
    assert regime in ("RISK_OFF", "LIQUIDITY_CONTRACTION")


def test_regime_inflationary_when_cpi_hot():
    r = RegimeFactors(vix=20.0, yield_curve=0.5, spy_30d_return=0.01, cpi_mom_pct=0.6, ten_year=4.5, dxy=105.0)
    regime, _, _ = classify_regime(r)
    assert regime == "INFLATIONARY"


def test_regime_liquidity_contraction_with_inverted_curve_and_m2_decline():
    r = RegimeFactors(vix=22.0, yield_curve=-0.5, spy_30d_return=0.0, m2_yoy_pct=-1.5)
    regime, _, _ = classify_regime(r)
    assert regime == "LIQUIDITY_CONTRACTION"


def test_regime_stagflationary_triad():
    r = RegimeFactors(vix=22.0, yield_curve=0.0, spy_30d_return=-0.04, cpi_mom_pct=0.7, ten_year=4.8)
    regime, _, _ = classify_regime(r)
    assert regime == "STAGFLATIONARY"


def test_regime_neutral_when_no_signals():
    r = RegimeFactors()
    regime, _, _ = classify_regime(r)
    assert regime == "NEUTRAL"


def test_cycle_phase_early_when_tech_leads():
    table = [
        {"etf": "XLK", "status": "LEADING"},
        {"etf": "XLY", "status": "LEADING"},
        {"etf": "XLU", "status": "LAGGING"},
    ]
    assert _cycle_phase(table) == "EARLY"


def test_cycle_phase_late_when_energy_leads():
    table = [
        {"etf": "XLE", "status": "LEADING"},
        {"etf": "XLB", "status": "NEUTRAL"},
        {"etf": "XLK", "status": "LAGGING"},
    ]
    assert _cycle_phase(table) == "LATE"


def test_cycle_phase_recession_when_defensives_lead():
    table = [
        {"etf": "XLP", "status": "LEADING"},
        {"etf": "XLU", "status": "LEADING"},
        {"etf": "XLV", "status": "LEADING"},
    ]
    assert _cycle_phase(table) == "RECESSION"


def test_cycle_phase_default_mid():
    assert _cycle_phase([]) == "MID"
