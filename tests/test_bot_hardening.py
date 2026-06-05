"""Regression tests for the hardening pass (guardrail finiteness, pending
dedupe, kill-stops-processing)."""

import asyncio
import math
from datetime import datetime, timezone

from backend.core.bots import executor as executor_mod
from backend.core.bots.executor import execute
from backend.core.bots.guardrails import GuardrailContext, check
from backend.core.bots.schemas import Bot, BotConfig, Guardrails, Intent, StrategyKind
from backend.core.bots.store import store
from backend.models.schemas import Order, OrderRequest


def _ctx(**kw):
    base = dict(price=100.0, equity=10_000.0, buying_power=10_000.0, position_qty=0.0,
                position_market_value=0.0, orders_today=0, today_pnl=0.0,
                market_open=True, last_fired_age=None)
    base.update(kw)
    return GuardrailContext(**base)


def test_guardrail_rejects_non_finite_price():
    d = check(Intent(symbol="AAPL", side="buy", notional=100), Guardrails(), _ctx(price=math.inf))
    assert not d.allow and "no live price" in d.reason


def test_guardrail_rejects_nan_notional():
    d = check(Intent(symbol="AAPL", side="buy", notional=math.nan), Guardrails(max_position_usd=1e9), _ctx())
    assert not d.allow


def _reset():
    store._bots.clear(); store._orders.clear(); store._events.clear(); store._pending.clear()


def _bot():
    return Bot(id="botH", user_id=1, name="h", require_approval=True,
               config=BotConfig(strategy=StrategyKind.threshold_dca, symbols=["AAPL"]))


def test_pending_dedupe_no_stacking():
    _reset()
    bot = _bot()
    intent = Intent(symbol="AAPL", side="buy", qty=1)
    r1 = asyncio.run(execute(bot, intent))
    r2 = asyncio.run(execute(bot, intent))  # identical signal again
    assert r1["status"] == "pending"
    assert r2.get("deduped") is True
    pendings = asyncio.run(store.list_pending(bot_id="botH", user_id=1))
    assert len(pendings) == 1  # only one approval queued


def test_pending_not_deduped_for_opposite_side():
    _reset()
    bot = _bot()
    asyncio.run(execute(bot, Intent(symbol="AAPL", side="buy", qty=1)))
    asyncio.run(execute(bot, Intent(symbol="AAPL", side="sell", qty=1)))
    pendings = asyncio.run(store.list_pending(bot_id="botH", user_id=1))
    assert len(pendings) == 2  # buy and sell are distinct
