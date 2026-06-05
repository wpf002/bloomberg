"""The hard safety gate. Every proposed intent passes through `check()`
before it can be executed. Rejections carry a human-readable reason that is
logged to bot_events. A daily-loss breach sets `kill=True` so the manager
auto-pauses the bot.

This is the load-bearing safety layer for real money. The deterministic
strategies and the LLM advisor only *propose*; guardrails *dispose*.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .schemas import Guardrails, Intent


@dataclass
class GuardrailContext:
    price: float
    equity: float
    buying_power: float
    position_qty: float = 0.0
    position_market_value: float = 0.0
    orders_today: int = 0
    today_pnl: float = 0.0          # realized+unrealized P&L vs start of day
    market_open: bool = True
    last_fired_age: float | None = None  # seconds since this symbol last traded; None = never


@dataclass
class Decision:
    allow: bool
    reason: str = ""
    kill: bool = False
    intent: Intent | None = None  # possibly size-adjusted


def _notional(intent: Intent, price: float) -> float:
    if intent.notional is not None:
        return float(intent.notional)
    if intent.qty is not None:
        return float(intent.qty) * price
    return 0.0


def check(intent: Intent, gr: Guardrails, ctx: GuardrailContext,
          *, config_symbols: list[str] | None = None) -> Decision:
    sym = intent.symbol.upper()
    side = intent.side.lower()

    # 1. Daily-loss kill-switch — evaluated first; a breach pauses the bot
    #    regardless of the specific intent.
    if gr.daily_loss_limit_usd is not None and ctx.today_pnl <= -abs(gr.daily_loss_limit_usd):
        return Decision(False, f"daily loss limit hit ({ctx.today_pnl:.2f} ≤ -{gr.daily_loss_limit_usd:.2f})", kill=True)

    # 2. Symbol allowlist (falls back to the bot's configured symbols).
    allow = [s.upper() for s in (gr.symbol_allowlist or config_symbols or [])]
    if allow and sym not in allow:
        return Decision(False, f"{sym} not in allowlist")

    # 3. Per-symbol cooldown.
    if ctx.last_fired_age is not None and ctx.last_fired_age < gr.per_symbol_cooldown_seconds:
        return Decision(False, f"cooldown: {ctx.last_fired_age:.0f}s < {gr.per_symbol_cooldown_seconds}s")

    # 4. Orders/day cap.
    if ctx.orders_today >= gr.max_orders_per_day:
        return Decision(False, f"max orders/day reached ({ctx.orders_today}/{gr.max_orders_per_day})")

    # 5. Market hours (extended-hours must be explicitly enabled).
    if not ctx.market_open and not gr.allow_extended_hours:
        return Decision(False, "market closed and extended-hours disabled")

    if ctx.price <= 0:
        return Decision(False, "no live price")

    # Sells that reduce an existing position bypass the position-size / buying
    # power caps (you can always exit). Cap the sell to the held quantity.
    if side == "sell":
        if ctx.position_qty <= 0:
            return Decision(False, "no position to sell")
        qty = intent.qty if intent.qty is not None else (ctx.position_qty)
        qty = min(qty, ctx.position_qty)
        if qty <= 0:
            return Decision(False, "sell qty resolves to zero")
        return Decision(True, intent=intent.model_copy(update={"qty": qty, "notional": None}))

    # 6. Buy-side sizing. Resolve to a notional, then to a fractional qty.
    notional = _notional(intent, ctx.price)
    if notional <= 0:
        return Decision(False, "buy notional resolves to zero")

    # Position notional cap.
    projected = ctx.position_market_value + notional
    if projected > gr.max_position_usd:
        return Decision(False, f"position cap: {projected:.0f} > {gr.max_position_usd:.0f}")
    if gr.max_position_pct is not None and ctx.equity > 0:
        pct = projected / ctx.equity * 100.0
        if pct > gr.max_position_pct:
            return Decision(False, f"position {pct:.1f}% > {gr.max_position_pct:.1f}% of equity")

    # Buying-power check.
    if notional > ctx.buying_power:
        return Decision(False, f"insufficient buying power ({notional:.0f} > {ctx.buying_power:.0f})")

    qty = round(notional / ctx.price, 4)
    if qty <= 0:
        return Decision(False, "buy qty resolves to zero")
    return Decision(True, intent=intent.model_copy(update={"qty": qty, "notional": None}))
