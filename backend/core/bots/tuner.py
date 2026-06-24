"""Parameter self-tuner for trading bots (Piece 2 + 3 of the learning engine).

After TUNE_THRESHOLD new trade outcomes, runs a grid search over the strategy's
tunable parameters against recent price history. Stores the best param set per
(bot_id, regime) so the manager can overlay regime-appropriate params at eval
time. Parameters are capped to ±MAX_DRIFT of their base value to prevent wild
swings.

Scoring: Calmar-like ratio = pnl_pct / max(max_drawdown_pct, 1.0).
Requires at least MIN_BARS of price history and MIN_TRADES backtested trades.
"""

from __future__ import annotations

import itertools
import logging
from typing import Any

from .backtest import run_backtest
from .outcomes import outcome_store
from .schemas import Bot, BotConfig, LearnedParams, StrategyKind, TuneResult

logger = logging.getLogger(__name__)

TUNE_THRESHOLD = 20
MIN_BARS = 40
MIN_TRADES = 3
MAX_DRIFT = 0.5   # params can shift at most ±50% from their base value

# Tunable param grid per strategy. Only keys listed here are searched;
# all other params keep the user's configured value unchanged.
_GRIDS: dict[StrategyKind, dict[str, list[float]]] = {
    StrategyKind.threshold_dca: {
        "drop_pct": [1.0, 1.5, 2.0, 2.5, 3.0],
    },
    StrategyKind.ma_crossover: {
        "fast": [5.0, 8.0, 10.0, 15.0],
        "slow": [20.0, 30.0, 50.0],
    },
    StrategyKind.rsi_reversion: {
        "period": [10.0, 14.0, 20.0],
        "low":    [25.0, 30.0, 35.0],
        "high":   [65.0, 70.0, 75.0],
    },
    StrategyKind.bollinger: {
        "period": [15.0, 20.0, 25.0],
        "std":    [1.5, 2.0, 2.5],
    },
    StrategyKind.breakout: {
        "lookback": [10.0, 15.0, 20.0, 30.0],
    },
}


def _score(result) -> float:
    """Calmar-like score: return / drawdown. Returns -999 for thin results."""
    if result.num_trades < MIN_TRADES:
        return -999.0
    dd = max(result.max_drawdown_pct, 1.0)
    return result.pnl_pct / dd


def _clamp(value: float, base: float) -> float:
    """Restrict value to ±MAX_DRIFT fraction of base."""
    if base == 0:
        return value
    lo = base * (1.0 - MAX_DRIFT)
    hi = base * (1.0 + MAX_DRIFT)
    return max(lo, min(hi, value))


def _grid_search(bot: Bot, closes: list[float]) -> tuple[dict[str, Any], float]:
    """Exhaustive grid search; returns (best_overlay_params, best_score)."""
    strategy = bot.config.strategy
    grid = _GRIDS.get(strategy)
    if not grid:
        return {}, -999.0

    base_params = dict(bot.config.params)
    best_overlay: dict[str, Any] = {}
    best_score = -999.0

    keys = list(grid.keys())
    for combo in itertools.product(*[grid[k] for k in keys]):
        candidate = dict(base_params)
        for k, v in zip(keys, combo):
            base_v = float(base_params.get(k, v))
            candidate[k] = _clamp(float(v), base_v)

        # ma_crossover: skip if fast >= slow (invalid cross)
        if strategy == StrategyKind.ma_crossover:
            if candidate.get("fast", 0) >= candidate.get("slow", 1):
                continue

        config = BotConfig(
            strategy=strategy,
            symbols=bot.config.symbols,
            params=candidate,
        )
        sym = bot.config.symbols[0] if bot.config.symbols else "SIM"
        result = run_backtest(config, closes, symbol=sym)
        s = _score(result)
        if s > best_score:
            best_score = s
            best_overlay = {k: candidate[k] for k in keys}

    return best_overlay, best_score


async def tune(bot: Bot, closes: list[float], regime: str = "any") -> TuneResult:
    """Run a grid search for bot over closes and save the best params if improved."""
    if len(closes) < MIN_BARS:
        return TuneResult(
            bot_id=bot.id, regime=regime, params={},
            score=-999.0, trades_used=len(closes), improved=False,
        )

    best_overlay, best_score = _grid_search(bot, closes)

    existing = await outcome_store.get_learned(bot.id, regime)
    improved = bool(best_overlay) and best_score > (existing.score if existing else -999.0)

    if improved:
        merged = {**bot.config.params, **best_overlay}
        learned = LearnedParams(
            bot_id=bot.id,
            regime=regime,
            params=merged,
            score=round(best_score, 4),
            trades=len(closes),
        )
        await outcome_store.save_learned(learned)
        logger.info(
            "bot %s tuned — regime=%s score=%.3f overlay=%s",
            bot.id, regime, best_score, best_overlay,
        )

    return TuneResult(
        bot_id=bot.id,
        regime=regime,
        params={**bot.config.params, **best_overlay},
        score=round(best_score, 4),
        trades_used=len(closes),
        improved=improved,
    )


async def maybe_tune(bot: Bot, closes: list[float], regime: str = "any") -> TuneResult | None:
    """Tune only if TUNE_THRESHOLD new outcomes have accumulated since the last run."""
    count = await outcome_store.count_since_last_tune(bot.id)
    if count < TUNE_THRESHOLD:
        return None
    return await tune(bot, closes, regime)
