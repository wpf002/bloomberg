"""End-to-end pipeline test: a quote tick driven all the way through
BotManager._on_tick → strategy → guardrails → executor → order/pending.

Per-component unit tests exist elsewhere; this proves the whole chain wires
together (the integration our unit tests don't cover), with the broker +
market-data source + store all faked so nothing hits the network.
"""

import asyncio
from datetime import datetime, timezone

import pytest

from importlib import import_module

# NB: `backend.core.bots.__init__` exports the `manager` *instance*, which
# shadows the submodule under attribute access. Pull the real module so we can
# monkeypatch its module-level resolve_execution_broker / market_data_source.
manager_mod = import_module("backend.core.bots.manager")
from backend.core.bots.coordination import leader_lock
from backend.core.bots.manager import BotManager
from backend.core.bots.schemas import Bot, BotConfig, Guardrails, StrategyKind
from backend.core.bots.store import store
from backend.models.schemas import Account, Order, OrderRequest, Position, Quote


class FakeBroker:
    name = "alpaca"
    mode = "paper"

    def __init__(self, equity=10_000.0, buying_power=10_000.0, positions=None):
        self._account = Account(equity=equity, last_equity=equity, buying_power=buying_power,
                                cash=buying_power, portfolio_value=equity)
        self._positions = positions or []
        self.placed: list[OrderRequest] = []

    def credentials_configured(self):
        return True

    async def get_account(self):
        return self._account

    async def get_positions(self):
        return self._positions

    async def place_order(self, req: OrderRequest) -> Order:
        self.placed.append(req)
        return Order(id="ord-e2e", client_order_id=req.client_order_id, symbol=req.symbol,
                     side=req.side, type=req.type, time_in_force=req.time_in_force,
                     qty=req.qty, status="accepted", submitted_at=datetime.now(timezone.utc))


class FakeData:
    """Market-data source double: bars + quote (with previous_close)."""

    def __init__(self, prev_close=100.0, closes=None):
        self._prev_close = prev_close
        self._closes = closes or []

    async def get_stock_quote(self, symbol):
        return Quote(symbol=symbol, price=self._closes[-1] if self._closes else self._prev_close,
                     previous_close=self._prev_close, timestamp=datetime.now(timezone.utc))

    async def get_stock_bars(self, symbol, period="3mo", interval="1d"):
        from backend.models.schemas import QuoteHistoryPoint
        out = []
        for c in self._closes:
            out.append(QuoteHistoryPoint(timestamp=datetime.now(timezone.utc), open=c, high=c, low=c, close=c, volume=0))
        return out


def _reset_store():
    store._bots.clear(); store._orders.clear(); store._events.clear(); store._pending.clear()


def _install(monkeypatch, broker, data):
    monkeypatch.setattr(manager_mod, "resolve_execution_broker",
                        lambda *a, **k: _async(broker))
    monkeypatch.setattr(manager_mod, "market_data_source", lambda: data)
    # leader lock: force leader without redis
    monkeypatch.setattr(leader_lock, "_is_leader", True, raising=False)


def _async(value):
    async def _coro(*a, **k):
        return value
    return _coro()


def _make_bot(require_approval, strategy=StrategyKind.threshold_dca, params=None):
    return Bot(
        id="botE2E", user_id=1, name="e2e", require_approval=require_approval,
        config=BotConfig(strategy=strategy, symbols=["AAPL"],
                         params=params or {"drop_pct": 2.0, "notional": 500.0}),
        guardrails=Guardrails(max_position_usd=5000, max_orders_per_day=10,
                              per_symbol_cooldown_seconds=0, daily_loss_limit_usd=None),
    )


def test_threshold_dca_fires_through_full_pipeline_to_pending(monkeypatch):
    """Approve-first bot: a -3% tick must produce a pending action end-to-end."""
    _reset_store()
    broker = FakeBroker()
    data = FakeData(prev_close=100.0, closes=[97.0])  # price 97 = -3% vs prev close 100
    _install(monkeypatch, broker, data)
    bot = _make_bot(require_approval=True)
    asyncio.run(store.create_bot(bot))
    asyncio.run(store.set_status("botE2E", __import__("backend.core.bots.schemas", fromlist=["BotStatus"]).BotStatus.active, user_id=1))

    mgr = BotManager()
    asyncio.run(mgr._on_tick({"type": "trade", "symbol": "AAPL", "price": 97.0}))

    pendings = asyncio.run(store.list_pending(bot_id="botE2E", user_id=1))
    assert len(pendings) == 1, "DCA should propose a buy on a -3% drop from prev close"
    assert pendings[0].intent.side == "buy"
    assert broker.placed == []  # approve-first → nothing executed yet


def test_autonomous_bot_places_order_through_full_pipeline(monkeypatch):
    """Autonomous bot: the same tick should place a paper order via the broker."""
    _reset_store()
    broker = FakeBroker()
    data = FakeData(prev_close=100.0, closes=[97.0])
    _install(monkeypatch, broker, data)
    bot = _make_bot(require_approval=False)
    asyncio.run(store.create_bot(bot))
    from backend.core.bots.schemas import BotStatus
    asyncio.run(store.set_status("botE2E", BotStatus.active, user_id=1))

    mgr = BotManager()
    asyncio.run(mgr._on_tick({"type": "trade", "symbol": "AAPL", "price": 97.0}))

    assert len(broker.placed) == 1
    assert broker.placed[0].side == "buy" and broker.placed[0].symbol == "AAPL"
    orders = asyncio.run(store.list_orders("botE2E"))
    assert orders and orders[0].alpaca_order_id == "ord-e2e"


def test_guardrail_blocks_in_pipeline_and_records_reject(monkeypatch):
    """A position already at the cap must be rejected end-to-end (no order)."""
    _reset_store()
    pos = Position(symbol="AAPL", qty=60, avg_entry_price=100.0, current_price=97.0, market_value=5820.0)
    broker = FakeBroker(positions=[pos])  # market value 5820 > 5000 cap
    data = FakeData(prev_close=100.0, closes=[97.0])
    _install(monkeypatch, broker, data)
    bot = _make_bot(require_approval=False)
    asyncio.run(store.create_bot(bot))
    from backend.core.bots.schemas import BotStatus
    asyncio.run(store.set_status("botE2E", BotStatus.active, user_id=1))

    mgr = BotManager()
    asyncio.run(mgr._on_tick({"type": "trade", "symbol": "AAPL", "price": 97.0}))

    assert broker.placed == []  # blocked by position cap
    events = asyncio.run(store.list_events("botE2E"))
    assert any(e.kind == "reject" for e in events)


def test_non_leader_does_not_evaluate(monkeypatch):
    """A non-leader replica must stay passive (no orders)."""
    _reset_store()
    broker = FakeBroker()
    data = FakeData(prev_close=100.0, closes=[97.0])
    _install(monkeypatch, broker, data)
    monkeypatch.setattr(leader_lock, "_is_leader", False, raising=False)
    bot = _make_bot(require_approval=False)
    asyncio.run(store.create_bot(bot))
    from backend.core.bots.schemas import BotStatus
    asyncio.run(store.set_status("botE2E", BotStatus.active, user_id=1))

    mgr = BotManager()
    asyncio.run(mgr._on_tick({"type": "trade", "symbol": "AAPL", "price": 97.0}))
    assert broker.placed == []
    assert asyncio.run(store.list_pending(bot_id="botE2E", user_id=1)) == []
