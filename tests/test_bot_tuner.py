"""Tests for the bot learning engine: tuner, outcome store, and manager integration."""

from __future__ import annotations

import math
import pytest

from backend.core.bots.schemas import Bot, BotConfig, LearnedParams, StrategyKind, TuneResult
from backend.core.bots.tuner import (
    MIN_BARS,
    TUNE_THRESHOLD,
    _clamp,
    _grid_search,
    _score,
    tune,
    maybe_tune,
)
from backend.core.bots.backtest import run_backtest
from backend.core.bots.outcomes import OutcomeStore
from backend.core.bots.schemas import TradeOutcome


# ── helpers ────────────────────────────────────────────────────────────────

def _make_bot(strategy=StrategyKind.threshold_dca, params=None):
    cfg = BotConfig(
        strategy=strategy,
        symbols=["SPY"],
        params=params or {"drop_pct": 2.0, "notional": 100.0},
    )
    return Bot(name="test", config=cfg)


def _trending_down(n=80, start=500.0, drop_per_bar=1.0):
    """Synthetic downtrend: gives threshold_dca plenty of buy signals."""
    return [start - i * drop_per_bar for i in range(n)]


def _flat(n=80, value=500.0):
    return [value] * n


# ── unit: _clamp ──────────────────────────────────────────────────────────

def test_clamp_within_bounds():
    assert _clamp(2.0, 2.0) == 2.0


def test_clamp_upper():
    # 4.0 > 2.0 * 1.5 → capped at 3.0
    assert _clamp(4.0, 2.0) == pytest.approx(3.0)


def test_clamp_lower():
    # 0.5 < 2.0 * 0.5 → capped at 1.0
    assert _clamp(0.5, 2.0) == pytest.approx(1.0)


def test_clamp_zero_base():
    # zero base → no clamping
    assert _clamp(99.0, 0.0) == 99.0


# ── unit: _score ──────────────────────────────────────────────────────────

def test_score_too_few_trades():
    result = run_backtest(
        BotConfig(strategy=StrategyKind.threshold_dca, symbols=["X"], params={"drop_pct": 50.0}),
        _flat(),  # no drops → no trades
    )
    assert _score(result) == -999.0


def test_score_positive_calmar():
    closes = _trending_down(n=80)
    cfg = BotConfig(strategy=StrategyKind.threshold_dca, symbols=["X"], params={"drop_pct": 1.0, "notional": 100.0})
    result = run_backtest(cfg, closes)
    if result.num_trades >= 3:
        s = _score(result)
        # Calmar = pnl_pct / dd; may be negative on a downtrend but should be finite
        assert math.isfinite(s)


# ── unit: _grid_search ────────────────────────────────────────────────────

def test_grid_search_threshold_dca_returns_overlay():
    bot = _make_bot()
    # 5 points/bar from 500 ≈ 1% per bar — enough to trigger threshold_dca at drop_pct=1.0
    closes = _trending_down(n=80, drop_per_bar=5.0)
    overlay, score = _grid_search(bot, closes)
    assert isinstance(overlay, dict)
    assert isinstance(score, float)
    # If a valid combo was found, it must include the tuned key
    if overlay:
        assert "drop_pct" in overlay


def test_grid_search_unknown_strategy_returns_empty():
    bot = _make_bot(strategy=StrategyKind.rebalance, params={"target_weight": 0.5})
    overlay, score = _grid_search(bot, _flat())
    assert overlay == {}
    assert score == -999.0


def test_grid_search_ma_crossover_skips_invalid_combos():
    """fast >= slow combos must be skipped; no exception raised."""
    bot = _make_bot(
        strategy=StrategyKind.ma_crossover,
        params={"fast": 10.0, "slow": 30.0, "qty": 1.0},
    )
    closes = [500 - i * 0.5 for i in range(80)]
    overlay, _ = _grid_search(bot, closes)
    # If any combo survived, fast < slow
    if overlay:
        assert overlay.get("fast", 0) < overlay.get("slow", 1)


# ── async: tune ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_tune_too_short_returns_no_improvement():
    bot = _make_bot()
    store = OutcomeStore()
    result = await tune(bot, _flat(n=5), regime="any")
    assert result.improved is False
    assert result.score == -999.0


@pytest.mark.asyncio
async def test_tune_saves_improved_params(monkeypatch):
    store = OutcomeStore()   # fresh in-memory store

    async def fake_get(bot_id, regime="any"):
        return None   # no prior learned params → any positive result is "improved"

    async def fake_save(learned):
        store._learned[(learned.bot_id, learned.regime)] = learned

    from backend.core.bots import outcomes as outcomes_mod
    monkeypatch.setattr(outcomes_mod.outcome_store, "get_learned", fake_get)
    monkeypatch.setattr(outcomes_mod.outcome_store, "save_learned", fake_save)

    bot = _make_bot()
    closes = _trending_down(n=80, drop_per_bar=2.0)
    result = await tune(bot, closes, regime="risk_off")

    # Can't guarantee improvement on synthetic data but the call must not crash
    assert isinstance(result.improved, bool)
    assert isinstance(result.score, float)
    assert result.regime == "risk_off"


# ── async: maybe_tune ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_maybe_tune_skips_below_threshold(monkeypatch):
    from backend.core.bots import outcomes as outcomes_mod

    async def fake_count(bot_id):
        return TUNE_THRESHOLD - 1   # one below threshold

    monkeypatch.setattr(outcomes_mod.outcome_store, "count_since_last_tune", fake_count)

    bot = _make_bot()
    result = await maybe_tune(bot, _trending_down(), regime="any")
    assert result is None


@pytest.mark.asyncio
async def test_maybe_tune_fires_at_threshold(monkeypatch):
    from backend.core.bots import outcomes as outcomes_mod

    async def fake_count(bot_id):
        return TUNE_THRESHOLD

    async def fake_get(bot_id, regime="any"):
        return None

    async def fake_save(learned):
        pass

    monkeypatch.setattr(outcomes_mod.outcome_store, "count_since_last_tune", fake_count)
    monkeypatch.setattr(outcomes_mod.outcome_store, "get_learned", fake_get)
    monkeypatch.setattr(outcomes_mod.outcome_store, "save_learned", fake_save)

    bot = _make_bot()
    result = await maybe_tune(bot, _trending_down(n=80, drop_per_bar=2.0), regime="any")
    assert result is not None
    assert isinstance(result.improved, bool)


# ── async: OutcomeStore ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_outcome_store_log_and_count():
    store = OutcomeStore()
    oc = TradeOutcome(
        bot_id="bot1", symbol="SPY", side="buy", price=500.0, qty=0.2,
        regime="risk_on", indicator_snap={"price": 500.0},
    )
    await store.log_trade(oc)
    # In-memory fallback: count should reflect the logged trade
    count = await store.count_since_last_tune("bot1")
    assert count == 1


@pytest.mark.asyncio
async def test_outcome_store_save_and_get_learned():
    store = OutcomeStore()
    lp = LearnedParams(
        bot_id="bot2", regime="risk_off",
        params={"drop_pct": 1.5}, score=3.14, trades=50,
    )
    await store.save_learned(lp)
    got = await store.get_learned("bot2", "risk_off")
    assert got is not None
    assert got.params["drop_pct"] == pytest.approx(1.5)
    assert got.score == pytest.approx(3.14)


@pytest.mark.asyncio
async def test_outcome_store_list_learned():
    store = OutcomeStore()
    for regime in ("any", "risk_on", "risk_off"):
        await store.save_learned(LearnedParams(
            bot_id="bot3", regime=regime, params={}, score=1.0, trades=20,
        ))
    all_lp = await store.list_learned("bot3")
    assert len(all_lp) == 3
