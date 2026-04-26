"""Tests for the Phase-9.2 yield curve and Agency MBS endpoints.

We can't hit FRED in CI, so we exercise the route-module import surface
plus the helper functions that don't depend on live data: shape
classification, sparkline trimming, and WoW/YoY arithmetic.
"""

from __future__ import annotations

from datetime import date, timedelta

from backend.api.routes import fixed_income


def test_route_module_imports_clean():
    # Importing the route module pulls in scipy + numpy. If either is
    # missing this raises at import time and pytest will surface it.
    from backend.api import api_router  # noqa: F401
    assert hasattr(fixed_income, "yield_curve")
    assert hasattr(fixed_income, "agency_mbs")


def test_tenor_series_covers_all_required_fred_ids():
    required = {
        "DGS1MO", "DGS3MO", "DGS6MO",
        "DGS1", "DGS2", "DGS3", "DGS5", "DGS7",
        "DGS10", "DGS20", "DGS30",
    }
    have = {sid for sid, _, _ in fixed_income._TENOR_SERIES}
    assert required == have


def test_tenor_years_strictly_increasing():
    years = [yrs for _, _, yrs in fixed_income._TENOR_SERIES]
    assert years == sorted(years)
    assert len(set(years)) == len(years)


def test_mbs_series_covers_required_fred_ids():
    required_ids = {"MORTGAGE30US", "MORTGAGE15US", "MORTG", "BAMLC0A0CM", "BAMLH0A0HYM2"}
    have = {sid for sid, _ in fixed_income._MBS_SERIES}
    assert required_ids == have


def test_wow_yoy_change_returns_triple_with_dates():
    # Build a fake observation list with date attribute.
    class _P:
        def __init__(self, d, v):
            self.date = d
            self.value = v

    today = date(2026, 4, 15)
    pts = [
        _P(today - timedelta(days=400), 5.0),
        _P(today - timedelta(days=370), 6.0),
        _P(today - timedelta(days=10),  7.0),
        _P(today, 7.5),
    ]
    cur, wow, yoy = fixed_income._wow_yoy_change(pts)
    assert cur == 7.5
    # Both deltas relative to closest prior observation outside the window
    assert wow is not None
    assert yoy is not None
    # Year-ago value (6.0) is further below current than week-ago value (7.0),
    # so YoY change should exceed WoW change.
    assert yoy > wow


def test_sparkline_trims_to_requested_points():
    class _P:
        def __init__(self, d, v):
            self.date = d
            self.value = v

    pts = [_P(date(2026, 1, i % 28 + 1), float(i)) for i in range(1, 80)]
    spark = fixed_income._sparkline(pts, points=30)
    assert len(spark) == 30
    assert all("date" in r and "value" in r for r in spark)
