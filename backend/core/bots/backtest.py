"""Replay a strategy over historical bars — the "dry-run before you arm it"
preview. No broker calls, no orders: pure simulation over a close series so a
user can see how a bot *would* have behaved before risking anything.

The simulator walks the bar series, builds a StrategyContext from the window
up to each bar, runs the strategy, and fills proposed intents at that bar's
close. It tracks cash + a single position and reports P&L and max drawdown.
"""

from __future__ import annotations

from .schemas import BacktestResult, BacktestTrade, BotConfig, EquityPoint, StrategyKind
from .strategies import StrategyContext, evaluate


def run_backtest(
    config: BotConfig,
    closes: list[float],
    *,
    symbol: str | None = None,
    start_cash: float = 10_000.0,
    timestamps: list | None = None,
    warmup: int = 30,
) -> BacktestResult:
    sym = (symbol or (config.symbols[0] if config.symbols else "SIM")).upper()
    cash = start_cash
    qty = 0.0
    cost_basis = 0.0  # total dollars paid for the open position
    trades: list[BacktestTrade] = []
    equity_curve: list[float] = []

    n = len(closes)
    for i in range(n):
        price = closes[i]
        if price <= 0:
            continue
        equity = cash + qty * price
        equity_curve.append(equity)

        if i < warmup:
            continue

        avg = (cost_basis / qty) if qty > 0 else 0.0
        ctx = StrategyContext(
            symbol=sym,
            price=price,
            closes=closes[: i + 1],
            position_qty=qty,
            position_avg=avg,
            equity=equity,
            position_market_value=qty * price,
            reference_price=closes[i - 1] if i >= 1 else price,
            params=config.params,
        )
        for intent in evaluate(config.strategy, ctx):
            ts = timestamps[i] if timestamps and i < len(timestamps) else None
            if intent.side == "buy":
                notional = intent.notional if intent.notional is not None else (
                    (intent.qty or 0.0) * price)
                notional = min(notional, cash)
                if notional <= 0:
                    continue
                bought = notional / price
                qty += bought
                cost_basis += notional
                cash -= notional
                trades.append(BacktestTrade(ts=ts, side="buy", symbol=sym, qty=round(bought, 4), price=price, reason=intent.reason))
            elif intent.side == "sell" and qty > 0:
                sell_qty = intent.qty if intent.qty is not None else qty
                sell_qty = min(sell_qty, qty)
                if sell_qty <= 0:
                    continue
                proceeds = sell_qty * price
                # reduce cost basis proportionally
                cost_basis *= max(0.0, (qty - sell_qty) / qty)
                qty -= sell_qty
                cash += proceeds
                trades.append(BacktestTrade(ts=ts, side="sell", symbol=sym, qty=round(sell_qty, 4), price=price, reason=intent.reason))

    end_price = closes[-1] if closes else 0.0
    end_equity = cash + qty * end_price
    if not equity_curve:
        equity_curve = [start_cash]

    # max drawdown over the equity curve
    peak = equity_curve[0]
    max_dd = 0.0
    for e in equity_curve:
        peak = max(peak, e)
        if peak > 0:
            max_dd = max(max_dd, (peak - e) / peak)

    pnl = end_equity - start_cash
    # Downsample the equity curve to ~60 points so the UI chart stays light.
    step = max(1, len(equity_curve) // 60)
    curve = [EquityPoint(i=i, equity=round(e, 2)) for i, e in enumerate(equity_curve) if i % step == 0]
    if curve and curve[-1].i != len(equity_curve) - 1:
        curve.append(EquityPoint(i=len(equity_curve) - 1, equity=round(equity_curve[-1], 2)))

    return BacktestResult(
        symbol=sym,
        strategy=config.strategy if isinstance(config.strategy, StrategyKind) else StrategyKind(config.strategy),
        start_equity=round(start_cash, 2),
        end_equity=round(end_equity, 2),
        pnl=round(pnl, 2),
        pnl_pct=round(pnl / start_cash * 100.0, 2) if start_cash else 0.0,
        max_drawdown_pct=round(max_dd * 100.0, 2),
        num_trades=len(trades),
        bars=n,
        trades=trades,
        equity_curve=curve,
    )
