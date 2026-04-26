"""Intelligence layer — regime detection, fragility, capital flows, rotation.

Sits above the risk engine and converts raw signals into actionable views.

- Regime detection: classifies the current macro environment from a fixed
  basket of FRED series + VIX level + yield curve + DXY + CPI + M2.
- Fragility scoring: 0-100 per holding, blending volatility percentile,
  drawdown depth, VIX correlation, beta, and sector regime sensitivity.
- Capital flow inference: tops 13F-filer holdings deltas to surface
  sectors receiving institutional inflows vs outflows.
- Sector rotation: 11-GICS-ETF 30-day relative strength, mapped to a
  cycle phase (Early / Mid / Late / Recession).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import date as date_cls, timedelta
from typing import Any

import numpy as np
import pandas as pd

from ..data.sources import FredSource, get_alpaca_source
from ..models.schemas import Position
from .risk_engine import _bars_by_date, _build_price_frame, _beta_to_spy

logger = logging.getLogger(__name__)

_fred = FredSource()


SECTOR_ETFS = {
    "XLK": "Technology",
    "XLF": "Financials",
    "XLE": "Energy",
    "XLV": "Healthcare",
    "XLI": "Industrials",
    "XLY": "Consumer Discretionary",
    "XLP": "Consumer Staples",
    "XLU": "Utilities",
    "XLB": "Materials",
    "XLRE": "Real Estate",
    "XLC": "Communication Services",
}

# Sector regime sensitivity — used to nudge per-position fragility scores.
# Higher value = more vulnerable in the current regime. Calibration is
# qualitative; the goal is "consumer discretionary should look more
# fragile in a stagflation regime than utilities," not a precise factor model.
SECTOR_REGIME_SENS = {
    "RISK_ON":               {"XLK": 0.3, "XLY": 0.3, "XLC": 0.3, "XLF": 0.4, "XLI": 0.5, "XLE": 0.6, "XLV": 0.5, "XLP": 0.6, "XLU": 0.7, "XLB": 0.5, "XLRE": 0.5},
    "RISK_OFF":              {"XLK": 0.7, "XLY": 0.8, "XLC": 0.7, "XLF": 0.8, "XLI": 0.7, "XLE": 0.7, "XLV": 0.4, "XLP": 0.3, "XLU": 0.2, "XLB": 0.7, "XLRE": 0.7},
    "INFLATIONARY":          {"XLK": 0.6, "XLY": 0.7, "XLC": 0.5, "XLF": 0.4, "XLI": 0.4, "XLE": 0.2, "XLV": 0.5, "XLP": 0.4, "XLU": 0.6, "XLB": 0.3, "XLRE": 0.6},
    "LIQUIDITY_CONTRACTION": {"XLK": 0.8, "XLY": 0.7, "XLC": 0.7, "XLF": 0.6, "XLI": 0.6, "XLE": 0.5, "XLV": 0.4, "XLP": 0.3, "XLU": 0.4, "XLB": 0.6, "XLRE": 0.8},
    "STAGFLATIONARY":        {"XLK": 0.7, "XLY": 0.8, "XLC": 0.7, "XLF": 0.6, "XLI": 0.6, "XLE": 0.3, "XLV": 0.5, "XLP": 0.4, "XLU": 0.5, "XLB": 0.5, "XLRE": 0.7},
    "NEUTRAL":               {k: 0.5 for k in SECTOR_ETFS},
}


@dataclass
class RegimeFactors:
    vix: float | None = None
    yield_curve: float | None = None
    cpi_mom_pct: float | None = None
    ten_year: float | None = None
    dxy: float | None = None
    m2_yoy_pct: float | None = None
    spy_30d_return: float | None = None


# ── series helpers ──────────────────────────────────────────────────────


async def _series_latest(series_id: str) -> tuple[float | None, date_cls | None]:
    """Latest observation value + date for a FRED series. Returns
    (None, None) when FRED isn't configured or the series is empty."""
    try:
        s = await _fred.get_series(series_id, limit=600)
    except Exception as exc:
        logger.debug("fred series %s failed: %s", series_id, exc)
        return None, None
    obs = getattr(s, "observations", []) or []
    if not obs:
        return None, None
    last = obs[-1]
    return float(last.value), last.date


async def _series_mom_pct(series_id: str) -> float | None:
    """Month-over-month percent change for the series' last two points.
    Used for CPI MoM signal."""
    try:
        s = await _fred.get_series(series_id, limit=12)
    except Exception:
        return None
    obs = getattr(s, "observations", []) or []
    if len(obs) < 2:
        return None
    a, b = obs[-2].value, obs[-1].value
    if a == 0:
        return None
    return (b - a) / a * 100.0


async def _series_yoy_pct(series_id: str) -> float | None:
    """Year-over-year % change. Walks back 12 obs (≈12 months for monthly
    series, ≈12 days for daily — caller should pick the right series)."""
    try:
        s = await _fred.get_series(series_id, limit=24)
    except Exception:
        return None
    obs = getattr(s, "observations", []) or []
    if len(obs) < 13:
        return None
    a = obs[-13].value
    b = obs[-1].value
    if a == 0:
        return None
    return (b - a) / a * 100.0


async def _spy_30d_return() -> float | None:
    closes = await _bars_by_date("SPY", period="3mo")
    if not closes:
        return None
    ser = pd.Series(closes).sort_index()
    if ser.shape[0] < 22:
        return None
    return float(ser.iloc[-1] / ser.iloc[-22] - 1.0)


# ── regime classification ──────────────────────────────────────────────


async def _gather_regime_factors() -> RegimeFactors:
    vix, _ = await _series_latest("VIXCLS")
    spread, _ = await _series_latest("T10Y2Y")
    ten_year, _ = await _series_latest("DGS10")
    dxy, _ = await _series_latest("DTWEXBGS")
    cpi_mom = await _series_mom_pct("CPIAUCSL")
    m2_yoy = await _series_yoy_pct("M2SL")
    spy_30d = await _spy_30d_return()
    return RegimeFactors(
        vix=vix,
        yield_curve=spread,
        cpi_mom_pct=cpi_mom,
        ten_year=ten_year,
        dxy=dxy,
        m2_yoy_pct=m2_yoy,
        spy_30d_return=spy_30d,
    )


def classify_regime(f: RegimeFactors) -> tuple[str, float, list[str]]:
    """Returns (regime, confidence_0_to_1, contributing_factors)."""
    contributing: list[str] = []

    # Each rule contributes a score; the highest wins. Rules can fire
    # partially (e.g., VIX > 25 and yield curve inverted).
    scores = {
        "RISK_ON": 0.0,
        "RISK_OFF": 0.0,
        "INFLATIONARY": 0.0,
        "LIQUIDITY_CONTRACTION": 0.0,
        "STAGFLATIONARY": 0.0,
        "NEUTRAL": 0.1,  # tiebreaker baseline
    }

    if f.vix is not None:
        if f.vix < 18:
            scores["RISK_ON"] += 1.0
            contributing.append(f"VIX {f.vix:.1f} (LOW)")
        elif f.vix > 25:
            scores["RISK_OFF"] += 1.0
            scores["LIQUIDITY_CONTRACTION"] += 0.5
            contributing.append(f"VIX {f.vix:.1f} (ELEVATED)")
        else:
            contributing.append(f"VIX {f.vix:.1f} (MID)")

    if f.yield_curve is not None:
        if f.yield_curve > 0.2:
            scores["RISK_ON"] += 0.5
            contributing.append(f"10Y-2Y {f.yield_curve:+.2f}% (POSITIVE)")
        elif f.yield_curve < 0:
            scores["RISK_OFF"] += 0.5
            scores["LIQUIDITY_CONTRACTION"] += 1.0
            contributing.append(f"10Y-2Y {f.yield_curve:+.2f}% (INVERTED)")
        else:
            contributing.append(f"10Y-2Y {f.yield_curve:+.2f}% (FLAT)")

    if f.spy_30d_return is not None:
        if f.spy_30d_return > 0.03:
            scores["RISK_ON"] += 0.5
            contributing.append(f"SPY 30d {f.spy_30d_return*100:+.1f}% (RISING)")
        elif f.spy_30d_return < -0.03:
            scores["RISK_OFF"] += 0.5
            contributing.append(f"SPY 30d {f.spy_30d_return*100:+.1f}% (DECLINING)")
        else:
            contributing.append(f"SPY 30d {f.spy_30d_return*100:+.1f}% (FLAT)")

    if f.cpi_mom_pct is not None:
        if f.cpi_mom_pct > 0.4:
            scores["INFLATIONARY"] += 1.0
            contributing.append(f"CPI MoM {f.cpi_mom_pct:+.2f}% (HOT)")
        elif f.cpi_mom_pct < 0.1:
            contributing.append(f"CPI MoM {f.cpi_mom_pct:+.2f}% (SOFT)")
        else:
            contributing.append(f"CPI MoM {f.cpi_mom_pct:+.2f}%")

    if f.ten_year is not None and f.dxy is not None:
        if f.cpi_mom_pct is not None and f.cpi_mom_pct > 0.4 and f.ten_year > 4.0:
            scores["INFLATIONARY"] += 0.5
            contributing.append(f"10Y {f.ten_year:.2f}% (RISING INTO HOT CPI)")

    if f.m2_yoy_pct is not None:
        if f.m2_yoy_pct < 0:
            scores["LIQUIDITY_CONTRACTION"] += 1.0
            contributing.append(f"M2 YoY {f.m2_yoy_pct:+.2f}% (CONTRACTING)")
        else:
            contributing.append(f"M2 YoY {f.m2_yoy_pct:+.2f}%")

    # Stagflationary = inflation + risk-off + (proxy: SPY declining despite
    # hot CPI). We treat that combination as a separate regime even though
    # individual signals overlap with the others.
    if (
        f.cpi_mom_pct is not None
        and f.cpi_mom_pct > 0.4
        and f.spy_30d_return is not None
        and f.spy_30d_return < 0
        and f.vix is not None
        and f.vix > 20
    ):
        scores["STAGFLATIONARY"] += 1.5
        contributing.append("STAGFLATION TRIAD: HOT CPI + FALLING EQUITIES + ELEVATED VIX")

    # Decide winner.
    regime = max(scores, key=scores.get)
    total = sum(scores.values())
    confidence = scores[regime] / total if total > 0 else 0.0
    return regime, round(confidence, 3), contributing


async def regime_now() -> dict[str, Any]:
    factors = await _gather_regime_factors()
    regime, confidence, contributing = classify_regime(factors)
    return {
        "regime": regime,
        "confidence": confidence,
        "contributing_factors": contributing,
        "raw": {
            "vix": factors.vix,
            "yield_curve": factors.yield_curve,
            "ten_year": factors.ten_year,
            "dxy": factors.dxy,
            "cpi_mom_pct": factors.cpi_mom_pct,
            "m2_yoy_pct": factors.m2_yoy_pct,
            "spy_30d_return": factors.spy_30d_return,
        },
    }


# ── fragility ──────────────────────────────────────────────────────────


async def _vix_correlation(symbol: str) -> float | None:
    """30-day rolling correlation of `symbol`'s daily returns to VIX
    daily changes. Used as the regime-sensitivity input."""
    try:
        sym_close = await _bars_by_date(symbol, period="6mo")
        vix_series = await _fred.get_series("VIXCLS", limit=120)
    except Exception:
        return None
    if not sym_close or not getattr(vix_series, "observations", []):
        return None
    a = pd.Series(sym_close).sort_index()
    a.index = pd.to_datetime(a.index)
    vix = pd.Series({pt.date: pt.value for pt in vix_series.observations}).sort_index()
    vix.index = pd.to_datetime(vix.index)
    df = pd.concat([a, vix], axis=1).dropna()
    df.columns = ["sym", "vix"]
    if df.shape[0] < 30:
        return None
    r = df.pct_change().dropna().tail(60)
    if r.shape[0] < 20:
        return None
    return float(r["sym"].corr(r["vix"]))


def _vol_percentile(returns: pd.Series, window: int = 30) -> float | None:
    """Most-recent-window stdev expressed as a percentile against the
    full-history rolling stdev. ~0 = currently very calm; ~1 = the
    noisiest period in our window."""
    if returns.shape[0] < window * 2:
        return None
    rolling = returns.rolling(window).std().dropna()
    if rolling.empty:
        return None
    current = float(rolling.iloc[-1])
    rank = float((rolling <= current).mean())
    return rank


async def _position_fragility(
    symbol: str, regime: str, etf_to_sector: dict[str, str]
) -> dict[str, Any]:
    """0-100 fragility for one symbol. Each component is normalized
    [0,1] then weighted; the weighted sum × 100 is the score."""
    closes = await _bars_by_date(symbol, period="1y")
    if not closes:
        return {
            "symbol": symbol,
            "score": 50.0,
            "components": {"note": "no price history"},
            "high_risk": False,
        }
    ser = pd.Series(closes).sort_index()
    ser.index = pd.to_datetime(ser.index)
    rets = ser.pct_change().dropna()

    vol_pct = _vol_percentile(rets) or 0.5

    # Drawdown depth normalized 0-1 (assume -50% caps the score).
    running_max = ser.cummax()
    dd_curve = ser / running_max - 1.0
    dd_depth = float(min(0.0, dd_curve.iloc[-1]))
    dd_norm = min(1.0, abs(dd_depth) / 0.5)

    # VIX correlation: higher absolute correlation → more fragile.
    vix_corr = await _vix_correlation(symbol)
    vix_norm = abs(vix_corr) if vix_corr is not None else 0.5

    beta = await _beta_to_spy(symbol)
    beta_norm = min(1.0, abs(beta) / 2.0)  # β=2 is "as fragile as it gets"

    # Sector regime sensitivity: assume the symbol's sector via the ETF
    # mapping the user is most likely to know. We don't have a ticker→sector
    # map per holding so we approximate with a neutral 0.5; for ETF symbols
    # we look it up exactly.
    sector_sens = SECTOR_REGIME_SENS.get(regime, {}).get(symbol, 0.5)

    # Weights chosen so no single signal dominates. Sum to 1.0.
    weights = {"vol_pct": 0.25, "drawdown": 0.25, "vix_corr": 0.2, "beta": 0.15, "sector": 0.15}
    raw = (
        vol_pct * weights["vol_pct"]
        + dd_norm * weights["drawdown"]
        + vix_norm * weights["vix_corr"]
        + beta_norm * weights["beta"]
        + sector_sens * weights["sector"]
    )
    score = round(raw * 100.0, 1)
    return {
        "symbol": symbol,
        "score": score,
        "high_risk": score >= 70.0,
        "components": {
            "vol_percentile": round(vol_pct, 3),
            "drawdown_depth": round(dd_depth, 4),
            "vix_correlation": round(vix_corr, 3) if vix_corr is not None else None,
            "beta": round(beta, 3),
            "sector_regime_sensitivity": sector_sens,
        },
    }


async def fragility_now() -> dict[str, Any]:
    alpaca = get_alpaca_source()
    if not alpaca.credentials_configured():
        return {"portfolio_score": 0.0, "positions": [], "regime": None, "note": "alpaca creds missing"}
    positions: list[Position] = await alpaca.get_positions()
    regime_payload = await regime_now()
    regime = regime_payload["regime"]
    if not positions:
        return {"portfolio_score": 0.0, "positions": [], "regime": regime}

    etf_lookup = {sym: name for sym, name in SECTOR_ETFS.items()}
    per_pos_coros = [_position_fragility(p.symbol, regime, etf_lookup) for p in positions]
    per_pos = await asyncio.gather(*per_pos_coros)

    total_value = sum(float(p.market_value or 0.0) for p in positions) or 1.0
    weighted = sum(
        (float(p.market_value or 0.0) / total_value) * row["score"]
        for p, row in zip(positions, per_pos)
    )
    return {
        "regime": regime,
        "portfolio_score": round(weighted, 1),
        "positions": per_pos,
    }


# ── capital flow inference (13F) ───────────────────────────────────────


# Marquee 13F filers — using their Investment Adviser CIKs. We sum the top
# changes across all of them to get a rough sense of "where institutional
# money is rotating." Free EDGAR coverage; quarterly cadence.
TOP_13F_FILERS = [
    {"cik": "0001067983", "name": "Berkshire Hathaway"},
    {"cik": "0001364742", "name": "BlackRock"},
    {"cik": "0001029160", "name": "Vanguard Group"},
    {"cik": "0000093751", "name": "State Street"},
    {"cik": "0001350694", "name": "Bridgewater Associates"},
]


async def _filer_13f_holdings(cik: str) -> list[dict[str, Any]]:
    """Most recent 13F-HR holdings for a CIK. SEC EDGAR doesn't expose a
    structured 13F endpoint on the free API; we read the submissions
    list, find the latest 13F-HR accession, and return a stub list with
    the accession number so downstream rotation logic can at least
    surface "filer X most recently filed on date Y" without us having
    to parse the XML information table.

    Best-effort: returns an empty list when EDGAR is unreachable or the
    filer hasn't filed a 13F-HR.
    """
    import httpx

    from ..core.config import settings

    headers = {"User-Agent": settings.sec_user_agent, "Accept": "application/json"}
    url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers=headers)
        if resp.status_code != 200:
            return []
        recent = (resp.json() or {}).get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        accessions = recent.get("accessionNumber", [])
        dates = recent.get("filingDate", [])
        out = []
        for i, form in enumerate(forms):
            if (form or "").upper() in ("13F-HR", "13F-HR/A"):
                out.append(
                    {
                        "form": form,
                        "accession": accessions[i],
                        "filed": dates[i],
                    }
                )
                if len(out) >= 4:  # last 4 quarters is enough
                    break
        return out
    except Exception as exc:
        logger.debug("13F fetch failed for %s: %s", cik, exc)
        return []


async def capital_flows() -> dict[str, Any]:
    """Surface the institutional 13F filing cadence we can see from EDGAR
    plus a sector-relative-strength proxy for inflows/outflows. The
    relative-strength view is the more reliable signal — full 13F XML
    parsing is intentionally out of scope (heavy + offline-only useful)."""
    filer_results = await asyncio.gather(
        *[_filer_13f_holdings(f["cik"]) for f in TOP_13F_FILERS]
    )
    filings_summary = []
    for filer, results in zip(TOP_13F_FILERS, filer_results):
        latest = results[0] if results else None
        filings_summary.append(
            {
                "name": filer["name"],
                "cik": filer["cik"],
                "latest_13f": latest,
                "history_count": len(results),
            }
        )

    # Sector flow proxy: 13-week sector-ETF returns vs SPY. Sectors
    # dramatically outperforming SPY infer institutional inflows; under-
    # performers infer outflows. Free, fast, and the directional read is
    # what users care about.
    syms = list(SECTOR_ETFS.keys()) + ["SPY"]
    frame = await _build_price_frame(syms, period="6mo")
    df = frame.to_dataframe()
    flows = []
    if not df.empty and "SPY" in df.columns and df.shape[0] >= 65:
        spy_ret = float(df["SPY"].iloc[-1] / df["SPY"].iloc[-66] - 1.0)
        for etf, sector in SECTOR_ETFS.items():
            if etf not in df.columns:
                continue
            ser = df[etf].dropna()
            if ser.shape[0] < 22:
                continue
            ret = float(ser.iloc[-1] / ser.iloc[-min(66, ser.shape[0])] - 1.0)
            relative = ret - spy_ret
            flows.append(
                {
                    "etf": etf,
                    "sector": sector,
                    "etf_return_3m": ret,
                    "relative_to_spy": relative,
                    "direction": "INFLOW" if relative > 0.005 else "OUTFLOW" if relative < -0.005 else "FLAT",
                }
            )
        flows.sort(key=lambda r: -r["relative_to_spy"])

    return {
        "filers": filings_summary,
        "sector_flows": flows,
        "method": "Sector flow inferred from 13-week sector-ETF excess return vs SPY (proxy for institutional rotation).",
    }


# ── sector rotation ────────────────────────────────────────────────────


def _cycle_phase(rs_table: list[dict[str, Any]]) -> str:
    """Pick a cycle phase from the leaders + laggards.

    Rules (qualitative):
      - Tech/Discretionary/Industrials leading → Early/Mid Cycle
      - Energy/Materials leading → Late Cycle
      - Staples/Utilities/Healthcare leading → Recession
      - Otherwise NEUTRAL → Mid Cycle
    """
    if not rs_table:
        return "MID"
    leaders = {r["etf"] for r in rs_table[:3] if r["status"] == "LEADING"}
    if leaders & {"XLK", "XLY", "XLC"}:
        return "EARLY"
    if leaders & {"XLI", "XLB"}:
        return "MID"
    if leaders & {"XLE", "XLRE"}:
        return "LATE"
    if leaders & {"XLP", "XLU", "XLV"}:
        return "RECESSION"
    return "MID"


async def sector_rotation() -> dict[str, Any]:
    syms = list(SECTOR_ETFS.keys()) + ["SPY"]
    frame = await _build_price_frame(syms, period="3mo")
    df = frame.to_dataframe()
    if df.empty or "SPY" in df.columns is False or df.shape[0] < 22:
        return {"signals": [], "phase": "NEUTRAL"}

    spy = df["SPY"].dropna()
    spy_ret = float(spy.iloc[-1] / spy.iloc[-min(22, spy.shape[0])] - 1.0)

    signals = []
    for etf, sector in SECTOR_ETFS.items():
        if etf not in df.columns:
            continue
        ser = df[etf].dropna()
        if ser.shape[0] < 22:
            continue
        ret = float(ser.iloc[-1] / ser.iloc[-min(22, ser.shape[0])] - 1.0)
        rs = ret - spy_ret
        status = (
            "LEADING"
            if rs > 0.01
            else "LAGGING"
            if rs < -0.01
            else "NEUTRAL"
        )
        signals.append(
            {
                "etf": etf,
                "sector": sector,
                "return_30d": ret,
                "relative_strength": rs,
                "status": status,
            }
        )
    signals.sort(key=lambda r: -r["relative_strength"])
    phase = _cycle_phase(signals)
    return {
        "phase": phase,
        "signals": signals,
        "spy_return_30d": spy_ret,
    }
