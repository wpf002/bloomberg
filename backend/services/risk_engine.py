"""Institutional-grade portfolio risk analytics.

Produces, against the live Alpaca paper portfolio:

- Sector exposure (Finnhub-classified, fallback to Alpaca asset class).
- Correlation matrix across holdings using 90-day daily returns.
- Drawdown stats per position and portfolio-wide.
- VaR (95% / 99%) via historical simulation.
- CVaR / Expected Shortfall (95% / 99%).
- Stress tests against the 2008 crisis, 2020 COVID crash, and the 2022
  rate-shock period — replays the historical SPY return path scaled by
  per-position beta to estimate the portfolio impact.

All computations are deliberately dependency-light: numpy + pandas are
the only heavy lifters, and the rest reuses existing source adapters
and the normalizer. Beta is the symbol's 1y daily-return regression on
SPY, which keeps the math intelligible to non-quants.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import date as date_cls, datetime
from typing import Any, Iterable

import numpy as np
import pandas as pd

from ..data.sources import FinnhubSource, get_alpaca_source
from ..models.schemas import Position, QuoteHistoryPoint

logger = logging.getLogger(__name__)


# Stress periods chosen from public Alpaca/IEX-feed coverage. We use SPY
# (always-tradable, deep history) as the proxy and re-scale by each
# position's beta so a high-beta name takes a bigger hit than a low-beta one.
STRESS_PERIODS = {
    "2008 GFC":       (date_cls(2008, 9, 1),  date_cls(2009, 3, 31)),
    "2020 COVID":     (date_cls(2020, 2, 19), date_cls(2020, 3, 23)),
    "2022 Rate Shock": (date_cls(2022, 1, 3), date_cls(2022, 10, 14)),
}

DEFAULT_LOOKBACK_DAYS = 90


@dataclass
class _PriceFrame:
    """Closes-by-date for a basket of symbols. Built once, reused across
    correlation, drawdown, VaR, stress."""

    symbols: list[str] = field(default_factory=list)
    closes: dict[str, dict[date_cls, float]] = field(default_factory=dict)

    def to_dataframe(self) -> pd.DataFrame:
        if not self.closes:
            return pd.DataFrame()
        s = {sym: pd.Series(rows) for sym, rows in self.closes.items() if rows}
        df = pd.DataFrame(s).sort_index()
        df.index = pd.to_datetime(df.index)
        return df


# ── data plumbing ──────────────────────────────────────────────────────


async def _bars_by_date(symbol: str, period: str = "1y") -> dict[date_cls, float]:
    alpaca = get_alpaca_source()
    try:
        bars: list[QuoteHistoryPoint] = await alpaca.get_stock_bars(
            symbol, period=period, interval="1d"
        )
    except Exception as exc:
        logger.debug("risk: bars failed for %s: %s", symbol, exc)
        return {}
    out: dict[date_cls, float] = {}
    for b in bars or []:
        try:
            out[b.timestamp.date()] = float(b.close)
        except Exception:
            continue
    return out


async def _build_price_frame(symbols: Iterable[str], period: str = "1y") -> _PriceFrame:
    syms = sorted({s.upper() for s in symbols if s})
    coros = [_bars_by_date(s, period=period) for s in syms]
    results = await asyncio.gather(*coros, return_exceptions=True)
    closes: dict[str, dict[date_cls, float]] = {}
    for sym, res in zip(syms, results):
        if isinstance(res, Exception):
            continue
        if res:
            closes[sym] = res
    return _PriceFrame(symbols=syms, closes=closes)


# ── sector classification ──────────────────────────────────────────────


_finnhub = FinnhubSource()


async def _sector_for(symbol: str) -> str:
    """Best-effort sector lookup. Finnhub /stock/profile2 is free-tier
    friendly. Falls back to 'Unknown' so a missing classification doesn't
    blank the panel."""
    if not _finnhub.enabled():
        return "Unknown"
    import httpx

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(
                "https://finnhub.io/api/v1/stock/profile2",
                params={"symbol": symbol.upper(), "token": _finnhub._api_key},
            )
        if resp.status_code != 200:
            return "Unknown"
        data = resp.json() or {}
        sector = (data.get("finnhubIndustry") or "").strip() or "Unknown"
        return sector
    except Exception as exc:
        logger.debug("sector lookup failed for %s: %s", symbol, exc)
        return "Unknown"


async def sector_exposure(positions: list[Position]) -> dict[str, Any]:
    """Sector breakdown weighted by market value."""
    if not positions:
        return {"total_value": 0.0, "sectors": [], "positions": []}
    sectors = await asyncio.gather(*[_sector_for(p.symbol) for p in positions])
    rows = []
    bucket: dict[str, float] = {}
    total = 0.0
    for p, sec in zip(positions, sectors):
        mv = float(p.market_value or 0.0)
        rows.append({"symbol": p.symbol, "sector": sec, "market_value": mv})
        bucket[sec] = bucket.get(sec, 0.0) + mv
        total += mv
    sector_rows = [
        {
            "sector": sec,
            "value": v,
            "weight": (v / total) if total > 0 else 0.0,
        }
        for sec, v in sorted(bucket.items(), key=lambda kv: -kv[1])
    ]
    return {
        "total_value": total,
        "sectors": sector_rows,
        "positions": rows,
    }


# ── correlation ─────────────────────────────────────────────────────────


def correlation_matrix(frame: _PriceFrame) -> dict[str, Any]:
    df = frame.to_dataframe()
    if df.empty or df.shape[1] < 2:
        return {"symbols": list(df.columns), "matrix": []}
    returns = df.pct_change().dropna(how="all")
    # Use the most recent ~90 trading days for a stable correlation read.
    returns = returns.tail(DEFAULT_LOOKBACK_DAYS)
    corr = returns.corr().round(3)
    return {
        "symbols": [str(c) for c in corr.columns],
        "matrix": corr.fillna(0.0).values.tolist(),
        "observations": int(returns.shape[0]),
    }


# ── drawdown ────────────────────────────────────────────────────────────


def _drawdown_series(prices: pd.Series) -> pd.Series:
    if prices.empty:
        return prices
    running_max = prices.cummax()
    return prices / running_max - 1.0


def drawdown_stats(
    frame: _PriceFrame, weights: dict[str, float]
) -> dict[str, Any]:
    df = frame.to_dataframe()
    if df.empty:
        return {"per_position": [], "portfolio": {}}

    per_pos = []
    for sym in df.columns:
        ser = df[sym].dropna()
        if ser.empty:
            continue
        dd = _drawdown_series(ser)
        max_dd = float(dd.min())
        cur_dd = float(dd.iloc[-1])
        # Drawdown duration: bars since last all-time-high.
        last_peak_idx = ser.idxmax()
        try:
            duration_days = int((ser.index[-1] - last_peak_idx).days)
        except Exception:
            duration_days = 0
        per_pos.append(
            {
                "symbol": sym,
                "max_drawdown": max_dd,
                "current_drawdown": cur_dd,
                "duration_days": duration_days,
            }
        )

    # Portfolio-wide: weighted daily return → cumulative NAV
    returns = df.pct_change().dropna(how="all").fillna(0.0)
    w = pd.Series({sym: float(weights.get(sym, 0.0)) for sym in returns.columns})
    if w.sum() > 0:
        w = w / w.sum()
    port_returns = returns.dot(w)
    nav = (1.0 + port_returns).cumprod()
    port_dd = _drawdown_series(nav)

    return {
        "per_position": per_pos,
        "portfolio": {
            "max_drawdown": float(port_dd.min()) if not port_dd.empty else 0.0,
            "current_drawdown": float(port_dd.iloc[-1]) if not port_dd.empty else 0.0,
            "duration_days": int((nav.index[-1] - nav.idxmax()).days)
            if not nav.empty
            else 0,
            "nav": [
                {"date": d.date().isoformat(), "value": float(v)}
                for d, v in nav.items()
            ],
            "drawdown_curve": [
                {"date": d.date().isoformat(), "value": float(v)}
                for d, v in port_dd.items()
            ],
        },
    }


# ── VaR / CVaR (historical simulation) ──────────────────────────────────


def var_cvar(
    frame: _PriceFrame, weights: dict[str, float]
) -> dict[str, Any]:
    df = frame.to_dataframe()
    if df.empty or df.shape[0] < 30:
        return {"observations": 0}
    returns = df.pct_change().dropna(how="all").fillna(0.0)
    w = pd.Series({sym: float(weights.get(sym, 0.0)) for sym in returns.columns})
    if w.sum() > 0:
        w = w / w.sum()
    port = returns.dot(w).dropna()
    if port.empty:
        return {"observations": 0}

    def _var(p: float) -> float:
        return float(np.quantile(port, p))

    def _cvar(p: float) -> float:
        threshold = _var(p)
        tail = port[port <= threshold]
        return float(tail.mean()) if not tail.empty else float(threshold)

    return {
        "observations": int(port.shape[0]),
        "var_95": _var(0.05),
        "var_99": _var(0.01),
        "cvar_95": _cvar(0.05),
        "cvar_99": _cvar(0.01),
        "mean_daily_return": float(port.mean()),
        "stdev_daily_return": float(port.std()),
    }


# ── stress tests ───────────────────────────────────────────────────────


async def _spy_path(start: date_cls, end: date_cls) -> pd.Series:
    """SPY closes between start and end. Pulled via Alpaca's bar history
    with a wide enough period to cover the requested window."""
    today = date_cls.today()
    days_back = (today - start).days
    if days_back <= 365:
        period = "2y"
    elif days_back <= 730:
        period = "5y"
    else:
        period = "max"
    rows = await _bars_by_date("SPY", period=period)
    if not rows:
        return pd.Series(dtype=float)
    ser = pd.Series(rows).sort_index()
    ser.index = pd.to_datetime(ser.index)
    mask = (ser.index >= pd.Timestamp(start)) & (ser.index <= pd.Timestamp(end))
    return ser[mask]


async def _beta_to_spy(symbol: str) -> float:
    """1-year daily-return beta of `symbol` to SPY. Defaults to 1.0 when
    we can't compute (no overlapping data)."""
    sym_close, spy_close = await asyncio.gather(
        _bars_by_date(symbol, period="1y"),
        _bars_by_date("SPY", period="1y"),
    )
    if not sym_close or not spy_close:
        return 1.0
    a = pd.Series(sym_close).sort_index()
    b = pd.Series(spy_close).sort_index()
    a.index = pd.to_datetime(a.index)
    b.index = pd.to_datetime(b.index)
    df = pd.concat([a, b], axis=1).dropna()
    df.columns = ["sym", "spy"]
    if df.shape[0] < 30:
        return 1.0
    r = df.pct_change().dropna()
    cov = float(np.cov(r["sym"], r["spy"])[0, 1])
    var = float(np.var(r["spy"]))
    if var <= 0:
        return 1.0
    return cov / var


async def stress_tests(positions: list[Position]) -> dict[str, Any]:
    if not positions:
        return {"scenarios": [], "current_value": 0.0}
    total = sum(float(p.market_value or 0.0) for p in positions)
    if total <= 0:
        return {"scenarios": [], "current_value": 0.0}

    # One beta per position, computed once and reused across all scenarios.
    betas = await asyncio.gather(*[_beta_to_spy(p.symbol) for p in positions])
    weights = {p.symbol: float(p.market_value or 0.0) / total for p in positions}

    scenarios: list[dict[str, Any]] = []
    # "Normal" baseline = recent 90-day cumulative SPY return for context.
    spy_recent = await _spy_path(
        date_cls.today().replace(year=date_cls.today().year - 1), date_cls.today()
    )
    if not spy_recent.empty:
        baseline_ret = float(spy_recent.iloc[-1] / spy_recent.iloc[0] - 1.0)
        scenarios.append(
            {
                "name": "Normal (1y SPY)",
                "spy_return": baseline_ret,
                "portfolio_return": baseline_ret,  # at beta-1 baseline
                "portfolio_pnl": baseline_ret * total,
            }
        )

    for name, (start, end) in STRESS_PERIODS.items():
        spy_path = await _spy_path(start, end)
        if spy_path.empty or spy_path.shape[0] < 2:
            scenarios.append(
                {
                    "name": name,
                    "spy_return": 0.0,
                    "portfolio_return": 0.0,
                    "portfolio_pnl": 0.0,
                    "note": "no SPY data for window (free-tier coverage gap)",
                }
            )
            continue
        spy_return = float(spy_path.iloc[-1] / spy_path.iloc[0] - 1.0)
        # Beta-weighted estimate: portfolio return ≈ Σ wᵢ * βᵢ * SPY_ret
        port_return = sum(
            weights[p.symbol] * beta * spy_return
            for p, beta in zip(positions, betas)
        )
        scenarios.append(
            {
                "name": name,
                "spy_return": spy_return,
                "portfolio_return": port_return,
                "portfolio_pnl": port_return * total,
            }
        )

    return {
        "current_value": total,
        "scenarios": scenarios,
        "betas": [
            {"symbol": p.symbol, "beta": float(b)}
            for p, b in zip(positions, betas)
        ],
    }


# ── public entry points called from the routes ────────────────────────


async def compute_exposure() -> dict[str, Any]:
    positions = await get_alpaca_source().get_positions()
    return await sector_exposure(positions)


async def compute_correlation() -> dict[str, Any]:
    positions = await get_alpaca_source().get_positions()
    syms = [p.symbol for p in positions if (p.market_value or 0) > 0]
    frame = await _build_price_frame(syms, period="1y")
    return correlation_matrix(frame)


async def compute_drawdown() -> dict[str, Any]:
    positions = await get_alpaca_source().get_positions()
    syms = [p.symbol for p in positions if (p.market_value or 0) > 0]
    if not syms:
        return {"per_position": [], "portfolio": {}}
    frame = await _build_price_frame(syms, period="1y")
    weights = {p.symbol: float(p.market_value or 0.0) for p in positions}
    return drawdown_stats(frame, weights)


async def compute_var() -> dict[str, Any]:
    positions = await get_alpaca_source().get_positions()
    syms = [p.symbol for p in positions if (p.market_value or 0) > 0]
    if not syms:
        return {"observations": 0}
    frame = await _build_price_frame(syms, period="1y")
    weights = {p.symbol: float(p.market_value or 0.0) for p in positions}
    return var_cvar(frame, weights)


async def compute_stress() -> dict[str, Any]:
    positions = await get_alpaca_source().get_positions()
    return await stress_tests(positions)


# ── V2.4: GEX / VEX (gamma + vanna exposure) ──────────────────────────


def _bsm_vanna(spot: float, strike: float, t_years: float, rate: float, sigma: float) -> float:
    """Black-Scholes vanna = -d1 * phi(d1) / (spot * sigma * sqrt(T)).

    Vanna measures how delta changes with implied vol. We use it to
    derive VEX when the upstream chain doesn't ship vanna directly.
    """
    import math

    if spot <= 0 or strike <= 0 or t_years <= 0 or sigma <= 0:
        return 0.0
    sqrt_t = math.sqrt(t_years)
    d1 = (math.log(spot / strike) + (rate + 0.5 * sigma * sigma) * t_years) / (sigma * sqrt_t)
    pdf_d1 = math.exp(-0.5 * d1 * d1) / math.sqrt(2.0 * math.pi)
    return -d1 * pdf_d1 / (spot * sigma * sqrt_t)


def compute_gex_profile(
    *,
    spot: float,
    contracts: list[Any],
    multiplier: int = 100,
) -> dict[str, Any]:
    """Per-strike GEX values + net GEX, flip point, max gamma strike.

    GEX per strike =
        open_interest * gamma * multiplier (100) * spot^2 * 0.01
    Calls add positive GEX (dealers long gamma → pinning).
    Puts add negative GEX (dealers short gamma → amplification).

    Returns:
        {
          strikes: [{strike, call_gex, put_gex, net_gex}, ...],
          net_gex: float,
          flip_point: float | None,
          max_gamma_strike: float | None,
          spot: float,
          walls: [{strike, gex}, ...],   # top 3 by |GEX|
        }
    """
    if spot is None or spot <= 0:
        return {
            "strikes": [], "net_gex": 0.0, "flip_point": None,
            "max_gamma_strike": None, "spot": spot, "walls": [],
        }
    by_strike: dict[float, dict[str, float]] = {}
    for c in contracts:
        strike = float(getattr(c, "strike", 0.0) or 0.0)
        if strike <= 0:
            continue
        oi = float(getattr(c, "open_interest", 0) or 0)
        gamma = getattr(c, "gamma", None)
        if gamma is None:
            continue
        gamma_val = float(gamma)
        gex = oi * gamma_val * multiplier * (spot * spot) * 0.01
        is_call = (getattr(c, "option_type", "") or "").lower() in ("call", "c")
        signed_gex = gex if is_call else -gex
        bucket = by_strike.setdefault(strike, {"call_gex": 0.0, "put_gex": 0.0})
        if is_call:
            bucket["call_gex"] += signed_gex
        else:
            bucket["put_gex"] += signed_gex
    rows = []
    for strike in sorted(by_strike.keys()):
        cg = by_strike[strike]["call_gex"]
        pg = by_strike[strike]["put_gex"]
        rows.append({
            "strike": strike,
            "call_gex": cg,
            "put_gex": pg,
            "net_gex": cg + pg,
        })
    net_gex = sum(r["net_gex"] for r in rows)
    flip = _gex_flip_point(rows)
    max_gamma_strike = None
    if rows:
        max_gamma_strike = max(rows, key=lambda r: abs(r["net_gex"]))["strike"]
    walls = sorted(rows, key=lambda r: abs(r["net_gex"]), reverse=True)[:3]
    walls = [{"strike": w["strike"], "gex": w["net_gex"]} for w in walls]
    return {
        "strikes": rows,
        "net_gex": net_gex,
        "flip_point": flip,
        "max_gamma_strike": max_gamma_strike,
        "spot": spot,
        "walls": walls,
    }


def _gex_flip_point(rows: list[dict]) -> float | None:
    """Linear interpolation between the two strikes that bracket the
    cumulative-net-GEX zero crossing."""
    if not rows:
        return None
    cum = 0.0
    prev_strike = None
    prev_cum = 0.0
    for r in rows:
        next_cum = cum + r["net_gex"]
        if prev_strike is not None and ((cum <= 0 < next_cum) or (cum >= 0 > next_cum)):
            # interpolate where cumulative crosses zero
            denom = next_cum - cum
            if denom == 0:
                return r["strike"]
            t = -cum / denom
            return prev_strike + t * (r["strike"] - prev_strike)
        prev_strike = r["strike"]
        prev_cum = cum
        cum = next_cum
    return None


def compute_vex_profile(
    *,
    spot: float,
    contracts: list[Any],
    multiplier: int = 100,
    rate: float = 0.045,
) -> dict[str, Any]:
    """Per-strike VEX values + net VEX + vol trigger.

    VEX per strike = open_interest * vanna * multiplier (100).
    """
    import math

    if spot is None or spot <= 0:
        return {"strikes": [], "net_vex": 0.0, "vol_trigger": None, "spot": spot}

    from ..core.bsm import year_fraction

    by_strike: dict[float, float] = {}
    for c in contracts:
        strike = float(getattr(c, "strike", 0.0) or 0.0)
        if strike <= 0:
            continue
        oi = float(getattr(c, "open_interest", 0) or 0)
        if oi <= 0:
            continue
        vanna = getattr(c, "vanna", None)
        if vanna is None:
            iv = float(getattr(c, "implied_volatility", 0.0) or 0.0)
            if iv <= 0:
                continue
            t = year_fraction(getattr(c, "expiration", "") or "")
            vanna = _bsm_vanna(spot, strike, t, rate, iv)
        is_call = (getattr(c, "option_type", "") or "").lower() in ("call", "c")
        # Calls: dealer is short calls → vanna sign flipped vs naive long.
        signed_vanna = float(vanna) if is_call else -float(vanna)
        vex = oi * signed_vanna * multiplier
        by_strike[strike] = by_strike.get(strike, 0.0) + vex
    rows = [{"strike": k, "vex": v} for k, v in sorted(by_strike.items())]
    net_vex = sum(r["vex"] for r in rows)
    vol_trigger = _vol_trigger(spot, contracts)
    return {
        "strikes": rows,
        "net_vex": net_vex,
        "vol_trigger": vol_trigger,
        "spot": spot,
    }


def _vol_trigger(spot: float, contracts: list[Any]) -> float | None:
    """Approximate the IV level at which net VEX flips sign.

    We re-evaluate VEX at a small grid of IV multipliers and return the
    first crossing; this is the operationally useful number — telling
    the user "if IV drops below X, dealers turn into buyers." Returns
    None when the chain has no IV info.
    """
    if not contracts:
        return None
    ivs = [float(getattr(c, "implied_volatility", 0.0) or 0.0) for c in contracts]
    ivs = [v for v in ivs if v > 0]
    if not ivs:
        return None
    base_iv = sum(ivs) / len(ivs)
    grid = [0.5, 0.7, 0.85, 1.0, 1.15, 1.3, 1.5]
    prev_sign = None
    prev_iv = None
    for mult in grid:
        iv = base_iv * mult
        net = 0.0
        for c in contracts:
            strike = float(getattr(c, "strike", 0.0) or 0.0)
            oi = float(getattr(c, "open_interest", 0) or 0)
            if strike <= 0 or oi <= 0:
                continue
            try:
                from ..core.bsm import year_fraction
                t = year_fraction(getattr(c, "expiration", "") or "")
                vanna = _bsm_vanna(spot, strike, t, 0.045, iv)
            except Exception:
                continue
            is_call = (getattr(c, "option_type", "") or "").lower() in ("call", "c")
            net += oi * (vanna if is_call else -vanna) * 100.0
        sign = 1 if net > 0 else (-1 if net < 0 else 0)
        if prev_sign is not None and sign != 0 and prev_sign != 0 and sign != prev_sign:
            return (prev_iv + iv) / 2.0
        prev_sign = sign
        prev_iv = iv
    return None


async def compute_gex(symbol: str) -> dict[str, Any]:
    """Public entry point — fetches the chain and returns the GEX profile."""
    alpaca = get_alpaca_source()
    chain = await alpaca.get_option_chain(symbol)
    contracts = list(chain.calls) + list(chain.puts)
    spot = chain.underlying_price or 0.0
    return compute_gex_profile(spot=spot, contracts=contracts)


async def compute_vex(symbol: str) -> dict[str, Any]:
    alpaca = get_alpaca_source()
    chain = await alpaca.get_option_chain(symbol)
    contracts = list(chain.calls) + list(chain.puts)
    spot = chain.underlying_price or 0.0
    return compute_vex_profile(spot=spot, contracts=contracts)


async def compute_gex_levels(symbol: str) -> dict[str, Any]:
    """Trimmed GEX response — flip point, max gamma, walls — used by
    the chart overlay and the AI Advisor context payload."""
    profile = await compute_gex(symbol)
    return {
        "symbol": symbol.upper(),
        "spot": profile.get("spot"),
        "flip_point": profile.get("flip_point"),
        "max_gamma_strike": profile.get("max_gamma_strike"),
        "walls": profile.get("walls", []),
        "net_gex": profile.get("net_gex"),
    }
