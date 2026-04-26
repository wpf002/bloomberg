"""Fixed income — Treasury auctions (free, public), FINRA TRACE corp
bond prints (free, requires registration at developer.finra.org), an
interpolated Treasury yield curve (cubic spline over FRED tenor points),
and Agency MBS / credit-spread metrics (FRED).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta
from typing import List

import numpy as np
from fastapi import APIRouter, HTTPException, Query
from scipy.interpolate import CubicSpline

from ...data.sources.finra_source import FinraSource
from ...data.sources.fred_source import FredSource
from ...data.sources.treasury_source import TreasurySource
from ...models.schemas import TraceAggregate, TreasuryAuction

logger = logging.getLogger(__name__)
router = APIRouter()

_treasury = TreasurySource()
_finra = FinraSource()
_fred = FredSource()

# FRED constant-maturity Treasury series, in tenor order. Years column is what
# the cubic spline interpolates over so the produced curve is calendar-time
# correct rather than spaced equally.
_TENOR_SERIES: list[tuple[str, str, float]] = [
    ("DGS1MO", "1M", 1 / 12),
    ("DGS3MO", "3M", 3 / 12),
    ("DGS6MO", "6M", 6 / 12),
    ("DGS1",   "1Y", 1.0),
    ("DGS2",   "2Y", 2.0),
    ("DGS3",   "3Y", 3.0),
    ("DGS5",   "5Y", 5.0),
    ("DGS7",   "7Y", 7.0),
    ("DGS10", "10Y", 10.0),
    ("DGS20", "20Y", 20.0),
    ("DGS30", "30Y", 30.0),
]

# Agency MBS + credit-spread series. The labels are echoed back so the panel
# can show short, readable headers instead of FRED IDs.
_MBS_SERIES: list[tuple[str, str]] = [
    ("MORTGAGE30US", "30Y Fixed Mortgage"),
    ("MORTGAGE15US", "15Y Fixed Mortgage"),
    ("MORTG",        "30Y Conv. Mortgage"),
    ("BAMLC0A0CM",   "ICE BofA US IG OAS"),
    ("BAMLH0A0HYM2", "ICE BofA US HY OAS"),
]


@router.get("/treasury/auctions", response_model=List[TreasuryAuction])
async def treasury_auctions(
    kind: str = Query("announced", description="announced (upcoming) | auctioned (recent results)"),
    limit: int = Query(20, ge=1, le=100),
) -> List[TreasuryAuction]:
    if kind == "announced":
        return await _treasury.announced(limit=limit)
    if kind == "auctioned":
        return await _treasury.auctioned(limit=limit)
    raise HTTPException(status_code=400, detail="kind must be 'announced' or 'auctioned'")


@router.get("/trace", response_model=List[TraceAggregate])
async def trace_aggregates(
    limit: int = Query(50, ge=1, le=500),
) -> List[TraceAggregate]:
    """FINRA Treasury aggregates (monthly first, weekly fallback).

    The free developer tier doesn't entitle accounts to corporate-bond
    TRACE prints — those need a paid subscription. The data we expose
    here are the public Treasury aggregates, which round out the
    Treasury-auction calendar above with actual trading activity.
    """
    if not _finra.credentials_configured():
        raise HTTPException(
            status_code=503,
            detail=(
                "FINRA not configured. Register a free developer "
                "account at https://developer.finra.org/ then set "
                "FINRA_API_KEY + FINRA_API_SECRET in .env."
            ),
        )
    return await _finra.treasury_aggregates(limit=limit)


@router.get("/status")
async def fixed_income_status() -> dict:
    """Cheap probe so the panel can say 'TRACE not configured' without a
    503 round-trip."""
    return {
        "treasury": True,  # public, always available
        "trace_configured": _finra.credentials_configured(),
        "fred_configured": _fred._enabled(),
    }


# ── yield curve (interpolated) ────────────────────────────────────────


def _latest_yield(observations) -> float | None:
    if not observations:
        return None
    last = observations[-1]
    val = getattr(last, "value", None)
    return float(val) if val is not None else None


@router.get("/curve")
async def yield_curve() -> dict:
    """Treasury yield curve assembled from FRED constant-maturity series.

    Returns the raw tenor points alongside a 100-point cubic-spline
    interpolation so the frontend can render a smooth curve with the
    auction points overlaid as dots. Also computes the canonical 2Y/10Y
    spread (in basis points) and a normal/inverted/flat classification
    so the panel can shade the curve appropriately.
    """
    series_results = await asyncio.gather(
        *[_fred.get_series(sid, limit=5) for sid, _, _ in _TENOR_SERIES],
        return_exceptions=True,
    )

    raw: list[dict] = []
    for (sid, label, years), result in zip(_TENOR_SERIES, series_results):
        if isinstance(result, Exception):
            logger.debug("yield curve: %s failed: %s", sid, result)
            continue
        yld = _latest_yield(getattr(result, "observations", None))
        if yld is None:
            continue
        raw.append({"series_id": sid, "label": label, "years": years, "yield": yld})

    if not raw:
        raise HTTPException(
            status_code=503,
            detail=(
                "FRED yield-curve data unavailable. Set FRED_API_KEY in .env "
                "or wait for the upstream rate limit to clear."
            ),
        )

    raw.sort(key=lambda r: r["years"])

    interpolated: list[dict] = []
    if len(raw) >= 2:
        xs = np.array([r["years"] for r in raw], dtype=float)
        ys = np.array([r["yield"] for r in raw], dtype=float)
        try:
            spline = CubicSpline(xs, ys, bc_type="natural", extrapolate=False)
            grid = np.linspace(xs.min(), xs.max(), 100)
            interpolated = [
                {"years": float(t), "yield": float(spline(t))}
                for t in grid
                if np.isfinite(spline(t))
            ]
        except Exception as exc:
            logger.warning("cubic spline failed: %s", exc)

    by_label = {r["label"]: r["yield"] for r in raw}
    y2 = by_label.get("2Y")
    y10 = by_label.get("10Y")
    spread_bps = round((y10 - y2) * 100, 1) if (y2 is not None and y10 is not None) else None
    if spread_bps is None:
        shape = "unknown"
    elif spread_bps < -10:
        shape = "inverted"
    elif spread_bps < 10:
        shape = "flat"
    else:
        shape = "normal"

    return {
        "raw": raw,
        "interpolated": interpolated,
        "spread_2y10y_bps": spread_bps,
        "shape": shape,
    }


# ── Agency MBS + credit spreads ──────────────────────────────────────


def _wow_yoy_change(observations) -> tuple[float | None, float | None, float | None]:
    """Return (current, week-over-week change, year-over-year change).

    Series are daily / weekly / monthly with mixed cadence, so we walk
    backward to the first observation older than the target horizon
    rather than assuming a fixed step size.
    """
    pts = list(observations or [])
    if not pts:
        return (None, None, None)
    current = pts[-1]
    cur_val = float(current.value)
    cur_date: date = current.date if hasattr(current.date, "isoformat") else None  # type: ignore
    if cur_date is None:
        return (cur_val, None, None)

    def _at_or_before(target: date) -> float | None:
        for p in reversed(pts):
            d = p.date
            if hasattr(d, "isoformat") and d <= target:
                return float(p.value)
        return None

    wow_target = cur_date - timedelta(days=7)
    yoy_target = cur_date - timedelta(days=365)
    prior_wk = _at_or_before(wow_target)
    prior_yr = _at_or_before(yoy_target)
    wow = (cur_val - prior_wk) if prior_wk is not None else None
    yoy = (cur_val - prior_yr) if prior_yr is not None else None
    return (cur_val, wow, yoy)


def _sparkline(observations, points: int = 30) -> list[dict]:
    """Tail the last `points` observations as {date, value} for sparklines."""
    pts = list(observations or [])[-points:]
    return [
        {"date": p.date.isoformat() if hasattr(p.date, "isoformat") else str(p.date), "value": float(p.value)}
        for p in pts
        if p.value is not None
    ]


@router.get("/mbs")
async def agency_mbs() -> dict:
    """Agency MBS rates plus IG/HY credit spread proxies.

    Returns a per-series block with the latest value, week-over-week and
    year-over-year deltas, and a sparkline. Also includes the mortgage-
    treasury spread time series (MORTGAGE30US − DGS10) so the frontend
    can render the dual-line spread chart.
    """
    if not _fred._enabled():
        raise HTTPException(
            status_code=503,
            detail="FRED not configured. Set FRED_API_KEY in .env.",
        )

    series_jobs = [_fred.get_series(sid, limit=400) for sid, _ in _MBS_SERIES]
    series_jobs.append(_fred.get_series("DGS10", limit=400))
    results = await asyncio.gather(*series_jobs, return_exceptions=True)
    dgs10 = results[-1]
    metric_results = results[:-1]

    metrics: list[dict] = []
    for (sid, label), result in zip(_MBS_SERIES, metric_results):
        if isinstance(result, Exception):
            logger.debug("MBS series %s failed: %s", sid, result)
            metrics.append({"series_id": sid, "label": label, "error": str(result)})
            continue
        cur, wow, yoy = _wow_yoy_change(getattr(result, "observations", None))
        metrics.append({
            "series_id": sid,
            "label": label,
            "units": getattr(result, "units", None),
            "current": cur,
            "wow": wow,
            "yoy": yoy,
            "sparkline": _sparkline(getattr(result, "observations", None), 60),
        })

    spread_series: list[dict] = []
    if not isinstance(dgs10, Exception) and not isinstance(metric_results[0], Exception):
        mort = {p.date: float(p.value) for p in (metric_results[0].observations or []) if p.value is not None}
        ten = {p.date: float(p.value) for p in (dgs10.observations or []) if p.value is not None}
        common = sorted(set(mort) & set(ten))[-180:]  # last ~6 months daily
        spread_series = [
            {
                "date": d.isoformat() if hasattr(d, "isoformat") else str(d),
                "mortgage": mort[d],
                "treasury_10y": ten[d],
                "spread": mort[d] - ten[d],
            }
            for d in common
        ]

    return {"metrics": metrics, "mortgage_treasury_spread": spread_series}
