"""Executor — approval gating, broker-routed placement, live gating."""

import asyncio
from datetime import datetime, timezone

import pytest

from backend.core.bots import executor as executor_mod
from backend.core.bots.executor import execute, place
from backend.core.bots.schemas import Bot, BotConfig, Intent, StrategyKind
from backend.core.bots.store import store
from backend.core.config import settings
from backend.models.schemas import Order, OrderRequest


class FakeBroker:
    name = "alpaca"
    mode = "paper"

    def __init__(self):
        self.placed: list[OrderRequest] = []

    def credentials_configured(self):
        return True

    async def place_order(self, req: OrderRequest) -> Order:
        self.placed.append(req)
        return Order(
            id="ord-123", client_order_id=req.client_order_id, symbol=req.symbol,
            side=req.side, type=req.type, time_in_force=req.time_in_force,
            qty=req.qty, status="accepted", submitted_at=datetime.now(timezone.utc),
        )


def _reset_store():
    store._bots.clear(); store._orders.clear(); store._events.clear(); store._pending.clear()


def _bot(require_approval=True, mode="paper") -> Bot:
    return Bot(
        id="botA", user_id=1, name="t", require_approval=require_approval, mode=mode,
        config=BotConfig(strategy=StrategyKind.threshold_dca, symbols=["AAPL"]),
    )


def test_approval_mode_queues_pending_and_does_not_trade():
    _reset_store()
    fake = FakeBroker()
    result = asyncio.run(execute(_bot(require_approval=True), Intent(symbol="AAPL", side="buy", qty=2), broker=fake))
    assert result["status"] == "pending"
    assert fake.placed == []
    pendings = asyncio.run(store.list_pending(bot_id="botA", user_id=1))
    assert len(pendings) == 1


def test_autonomous_places_via_injected_broker():
    _reset_store()
    fake = FakeBroker()
    result = asyncio.run(execute(_bot(require_approval=False), Intent(symbol="AAPL", side="buy", qty=2, reason="dip"), broker=fake))
    assert result["status"] == "placed"
    assert len(fake.placed) == 1 and fake.placed[0].qty == 2
    # deterministic client_order_id for idempotency
    assert fake.placed[0].client_order_id.startswith("bot-botA-AAPL-buy-")
    orders = asyncio.run(store.list_orders("botA"))
    assert orders and orders[0].alpaca_order_id == "ord-123"


def test_place_rejects_zero_qty():
    _reset_store()
    fake = FakeBroker()
    result = asyncio.run(place(_bot(require_approval=False), Intent(symbol="AAPL", side="buy", qty=0), broker=fake))
    assert result["status"] == "rejected"
    assert fake.placed == []


def test_live_bot_refused_without_master_switch(monkeypatch):
    _reset_store()
    monkeypatch.setattr(settings, "bots_allow_live", False, raising=False)
    # broker=None forces resolution; live + no flag → refused
    result = asyncio.run(execute(_bot(require_approval=False, mode="live"), Intent(symbol="AAPL", side="buy", qty=1)))
    assert result["status"] == "refused"
    events = asyncio.run(store.list_events("botA"))
    assert any(e.kind == "error" for e in events)
