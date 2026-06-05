"""Deterministic strategy primitives.

Each strategy is a pure function `evaluate(ctx) -> list[Intent]` over a
`StrategyContext`. No I/O, no broker calls — the manager builds the context
from live data and the backtester builds it from historical bars, so the
exact same logic drives both. This is what makes strategies unit-testable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from .schemas import Intent, StrategyKind


@dataclass
class StrategyContext:
    symbol: str
    price: float
    closes: list[float] = field(default_factory=list)  # historical closes, oldest→newest, incl. current
    position_qty: float = 0.0
    position_avg: float = 0.0
    equity: float = 0.0
    position_market_value: float = 0.0
    reference_price: float | None = None  # DCA anchor (e.g. prev close / session high)
    params: dict[str, Any] = field(default_factory=dict)


# ── indicator helpers ─────────────────────────────────────────────────────


def sma(values: list[float], period: int) -> float | None:
    if period <= 0 or len(values) < period:
        return None
    return sum(values[-period:]) / period


def rsi(values: list[float], period: int = 14) -> float | None:
    """Wilder's RSI. Returns None until there are at least `period+1` closes."""
    if period <= 0 or len(values) < period + 1:
        return None
    gains = 0.0
    losses = 0.0
    # seed with the first `period` deltas
    for i in range(1, period + 1):
        delta = values[i] - values[i - 1]
        if delta >= 0:
            gains += delta
        else:
            losses -= delta
    avg_gain = gains / period
    avg_loss = losses / period
    # Wilder smoothing across the remaining deltas
    for i in range(period + 1, len(values)):
        delta = values[i] - values[i - 1]
        gain = delta if delta > 0 else 0.0
        loss = -delta if delta < 0 else 0.0
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def stddev(values: list[float], period: int) -> float | None:
    """Population standard deviation of the last `period` values."""
    if period <= 0 or len(values) < period:
        return None
    window = values[-period:]
    mean = sum(window) / period
    var = sum((v - mean) ** 2 for v in window) / period
    return var ** 0.5


def _p(params: dict[str, Any], key: str, default: float) -> float:
    try:
        v = params.get(key, default)
        return float(v) if v is not None else float(default)
    except (TypeError, ValueError):
        return float(default)


# ── strategies ────────────────────────────────────────────────────────────


def threshold_dca(ctx: StrategyContext) -> list[Intent]:
    """Buy `notional` dollars whenever price falls `drop_pct` below the
    reference price (default: previous close). The Robinhood-style
    "buy $100 of X every time it drops 2%"."""
    drop_pct = _p(ctx.params, "drop_pct", 2.0)
    notional = _p(ctx.params, "notional", 100.0)
    ref = ctx.reference_price if ctx.reference_price else (ctx.closes[-2] if len(ctx.closes) >= 2 else ctx.price)
    if ref and ctx.price <= ref * (1.0 - drop_pct / 100.0):
        return [Intent(
            symbol=ctx.symbol, side="buy", notional=notional, type="market",
            reason=f"price {ctx.price:.2f} ≤ {drop_pct:.1f}% below ref {ref:.2f}",
        )]
    return []


def ma_crossover(ctx: StrategyContext) -> list[Intent]:
    """Golden/death cross of a fast vs slow SMA. Buys `qty` on a fresh
    bullish cross; sells the open position on a bearish cross."""
    fast = int(_p(ctx.params, "fast", 10))
    slow = int(_p(ctx.params, "slow", 30))
    qty = _p(ctx.params, "qty", 1.0)
    if len(ctx.closes) < slow + 1:
        return []
    fast_now, slow_now = sma(ctx.closes, fast), sma(ctx.closes, slow)
    fast_prev, slow_prev = sma(ctx.closes[:-1], fast), sma(ctx.closes[:-1], slow)
    if None in (fast_now, slow_now, fast_prev, slow_prev):
        return []
    crossed_up = fast_prev <= slow_prev and fast_now > slow_now
    crossed_down = fast_prev >= slow_prev and fast_now < slow_now
    if crossed_up:
        return [Intent(symbol=ctx.symbol, side="buy", qty=qty, type="market",
                       reason=f"SMA{fast} crossed above SMA{slow}")]
    if crossed_down and ctx.position_qty > 0:
        return [Intent(symbol=ctx.symbol, side="sell", qty=min(qty, ctx.position_qty), type="market",
                       reason=f"SMA{fast} crossed below SMA{slow}")]
    return []


def rsi_reversion(ctx: StrategyContext) -> list[Intent]:
    """Mean-reversion: buy when RSI is oversold, sell the position when
    overbought."""
    period = int(_p(ctx.params, "period", 14))
    low = _p(ctx.params, "low", 30.0)
    high = _p(ctx.params, "high", 70.0)
    qty = _p(ctx.params, "qty", 1.0)
    value = rsi(ctx.closes, period)
    if value is None:
        return []
    if value < low:
        return [Intent(symbol=ctx.symbol, side="buy", qty=qty, type="market",
                       reason=f"RSI {value:.1f} < {low:.0f} (oversold)")]
    if value > high and ctx.position_qty > 0:
        return [Intent(symbol=ctx.symbol, side="sell", qty=min(qty, ctx.position_qty), type="market",
                       reason=f"RSI {value:.1f} > {high:.0f} (overbought)")]
    return []


def take_profit_stop(ctx: StrategyContext) -> list[Intent]:
    """Exit an open position at a take-profit or stop-loss threshold relative
    to the average entry price."""
    if ctx.position_qty <= 0 or ctx.position_avg <= 0:
        return []
    tp = _p(ctx.params, "take_profit_pct", 10.0)
    sl = _p(ctx.params, "stop_loss_pct", 5.0)
    if ctx.price >= ctx.position_avg * (1.0 + tp / 100.0):
        return [Intent(symbol=ctx.symbol, side="sell", qty=ctx.position_qty, type="market",
                       reason=f"take-profit: {ctx.price:.2f} ≥ +{tp:.1f}% of {ctx.position_avg:.2f}")]
    if ctx.price <= ctx.position_avg * (1.0 - sl / 100.0):
        return [Intent(symbol=ctx.symbol, side="sell", qty=ctx.position_qty, type="market",
                       reason=f"stop-loss: {ctx.price:.2f} ≤ -{sl:.1f}% of {ctx.position_avg:.2f}")]
    return []


def bollinger(ctx: StrategyContext) -> list[Intent]:
    """Mean-reversion on Bollinger bands: buy when price closes below the lower
    band; sell the position when it closes above the upper band."""
    period = int(_p(ctx.params, "period", 20))
    mult = _p(ctx.params, "std", 2.0)
    qty = _p(ctx.params, "qty", 1.0)
    mid = sma(ctx.closes, period)
    sd = stddev(ctx.closes, period)
    if mid is None or sd is None or sd == 0:
        return []
    lower, upper = mid - mult * sd, mid + mult * sd
    if ctx.price < lower:
        return [Intent(symbol=ctx.symbol, side="buy", qty=qty, type="market",
                       reason=f"price {ctx.price:.2f} < lower band {lower:.2f}")]
    if ctx.price > upper and ctx.position_qty > 0:
        return [Intent(symbol=ctx.symbol, side="sell", qty=min(qty, ctx.position_qty), type="market",
                       reason=f"price {ctx.price:.2f} > upper band {upper:.2f}")]
    return []


def breakout(ctx: StrategyContext) -> list[Intent]:
    """Donchian breakout: buy when price exceeds the highest close of the prior
    `lookback` bars; sell the position when it falls below the lowest."""
    lookback = int(_p(ctx.params, "lookback", 20))
    qty = _p(ctx.params, "qty", 1.0)
    if len(ctx.closes) < lookback + 1:
        return []
    prior = ctx.closes[-(lookback + 1):-1]  # exclude the current close
    hi, lo = max(prior), min(prior)
    if ctx.price > hi:
        return [Intent(symbol=ctx.symbol, side="buy", qty=qty, type="market",
                       reason=f"breakout: {ctx.price:.2f} > {lookback}d high {hi:.2f}")]
    if ctx.price < lo and ctx.position_qty > 0:
        return [Intent(symbol=ctx.symbol, side="sell", qty=min(qty, ctx.position_qty), type="market",
                       reason=f"breakdown: {ctx.price:.2f} < {lookback}d low {lo:.2f}")]
    return []


def rebalance(ctx: StrategyContext) -> list[Intent]:
    """Drift the position toward a target weight of equity. `target_weight`
    is this symbol's share of the account (0..1); `band_pct` is the no-trade
    tolerance band so we don't churn on tiny drifts."""
    target_weight = _p(ctx.params, "target_weight", 0.0)
    band_pct = _p(ctx.params, "band_pct", 5.0)
    if ctx.equity <= 0 or ctx.price <= 0:
        return []
    target_value = ctx.equity * target_weight
    current_value = ctx.position_market_value or (ctx.position_qty * ctx.price)
    drift = current_value - target_value
    tolerance = ctx.equity * (band_pct / 100.0)
    if abs(drift) <= tolerance:
        return []
    if drift < 0:  # underweight → buy the gap
        return [Intent(symbol=ctx.symbol, side="buy", notional=abs(drift), type="market",
                       reason=f"underweight {current_value:.0f} vs target {target_value:.0f}")]
    # overweight → sell the gap (bounded by the position)
    qty = min(ctx.position_qty, abs(drift) / ctx.price)
    if qty <= 0:
        return []
    return [Intent(symbol=ctx.symbol, side="sell", qty=qty, type="market",
                   reason=f"overweight {current_value:.0f} vs target {target_value:.0f}")]


STRATEGIES: dict[StrategyKind, Callable[[StrategyContext], list[Intent]]] = {
    StrategyKind.threshold_dca: threshold_dca,
    StrategyKind.ma_crossover: ma_crossover,
    StrategyKind.rsi_reversion: rsi_reversion,
    StrategyKind.bollinger: bollinger,
    StrategyKind.breakout: breakout,
    StrategyKind.take_profit_stop: take_profit_stop,
    StrategyKind.rebalance: rebalance,
}


def evaluate(kind: StrategyKind, ctx: StrategyContext) -> list[Intent]:
    fn = STRATEGIES.get(kind)
    if fn is None:
        return []
    return [i.normalized() for i in fn(ctx)]
