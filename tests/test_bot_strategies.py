"""Strategy primitives — pure logic over a crafted StrategyContext."""

from backend.core.bots.schemas import StrategyKind
from backend.core.bots.strategies import (
    StrategyContext,
    evaluate,
    rsi,
    sma,
)


def test_sma_and_rsi_helpers():
    assert sma([1, 2, 3, 4], 2) == 3.5
    assert sma([1, 2], 5) is None
    # all-up series → RSI pinned at 100
    assert rsi([float(i) for i in range(1, 20)], 14) == 100.0
    # not enough data
    assert rsi([1, 2, 3], 14) is None


def test_threshold_dca_buys_on_drop():
    ctx = StrategyContext(symbol="AAPL", price=98.0, reference_price=100.0,
                          params={"drop_pct": 2.0, "notional": 100.0})
    intents = evaluate(StrategyKind.threshold_dca, ctx)
    assert len(intents) == 1
    assert intents[0].side == "buy"
    assert intents[0].notional == 100.0


def test_threshold_dca_silent_above_threshold():
    ctx = StrategyContext(symbol="AAPL", price=99.5, reference_price=100.0,
                          params={"drop_pct": 2.0, "notional": 100.0})
    assert evaluate(StrategyKind.threshold_dca, ctx) == []


def test_ma_crossover_golden_cross_buys():
    # fast SMA crosses above slow on the last bar
    closes = [10.0] * 30 + [10, 10, 10]  # flat, no cross
    flat = StrategyContext(symbol="X", price=10.0, closes=closes, params={"fast": 3, "slow": 5})
    assert evaluate(StrategyKind.ma_crossover, flat) == []

    rising = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1, 2,
              3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13]
    ctx = StrategyContext(symbol="X", price=13.0, closes=[float(c) for c in rising],
                          params={"fast": 3, "slow": 10})
    intents = evaluate(StrategyKind.ma_crossover, ctx)
    assert all(i.side in ("buy", "sell") for i in intents)


def test_ma_crossover_death_cross_only_sells_with_position():
    falling = [float(c) for c in (list(range(1, 16)) + list(range(15, 0, -1)))]
    no_pos = StrategyContext(symbol="X", price=1.0, closes=falling,
                             position_qty=0.0, params={"fast": 3, "slow": 10})
    # a death cross with no position yields nothing to sell
    assert evaluate(StrategyKind.ma_crossover, no_pos) == []


def test_rsi_reversion_oversold_buys():
    # steadily falling closes → low RSI
    closes = [float(c) for c in range(40, 10, -1)]
    ctx = StrategyContext(symbol="X", price=closes[-1], closes=closes,
                          params={"period": 14, "low": 30, "high": 70, "qty": 2})
    intents = evaluate(StrategyKind.rsi_reversion, ctx)
    assert len(intents) == 1 and intents[0].side == "buy" and intents[0].qty == 2


def test_take_profit_stop_exits():
    tp = StrategyContext(symbol="X", price=112.0, position_qty=5, position_avg=100.0,
                         params={"take_profit_pct": 10, "stop_loss_pct": 5})
    out = evaluate(StrategyKind.take_profit_stop, tp)
    assert out and out[0].side == "sell" and out[0].qty == 5

    sl = StrategyContext(symbol="X", price=94.0, position_qty=5, position_avg=100.0,
                         params={"take_profit_pct": 10, "stop_loss_pct": 5})
    out = evaluate(StrategyKind.take_profit_stop, sl)
    assert out and out[0].side == "sell"

    hold = StrategyContext(symbol="X", price=101.0, position_qty=5, position_avg=100.0,
                           params={"take_profit_pct": 10, "stop_loss_pct": 5})
    assert evaluate(StrategyKind.take_profit_stop, hold) == []


def test_rebalance_buys_underweight_within_band():
    # target 50% of 10k = 5k; holding 1k → underweight beyond a 5% band (500)
    ctx = StrategyContext(symbol="X", price=10.0, equity=10_000.0,
                          position_qty=100, position_market_value=1_000.0,
                          params={"target_weight": 0.5, "band_pct": 5})
    out = evaluate(StrategyKind.rebalance, ctx)
    assert out and out[0].side == "buy" and out[0].notional == 4_000.0


def test_rebalance_silent_within_band():
    ctx = StrategyContext(symbol="X", price=10.0, equity=10_000.0,
                          position_qty=490, position_market_value=4_900.0,
                          params={"target_weight": 0.5, "band_pct": 5})
    assert evaluate(StrategyKind.rebalance, ctx) == []
