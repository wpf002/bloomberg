"""Bot heartbeat: snapshot store roundtrip + status-note formatting + the
always-on watchdog that flags stale heartbeats."""

import asyncio
import time
from datetime import datetime, timedelta, timezone

from backend.core.bots import executor as executor_real
from backend.core.bots import health
from backend.core.bots.manager import BotManager
from backend.core.bots.schemas import Bot, BotConfig, StrategyKind


def test_health_write_read_roundtrip():
    async def go():
        await health.write("bot-1", {"note": "SPY 600 · +0.10%", "price": 600.0})
        snap = await health.read("bot-1")
        assert snap and snap["price"] == 600.0
        many = await health.read_many(["bot-1", "missing"])
        assert "bot-1" in many and "missing" not in many

    asyncio.run(go())


def _dca_bot():
    return Bot(
        user_id=1, name="SPY Bot",
        config=BotConfig(strategy=StrategyKind.threshold_dca, symbols=["SPY"], params={"drop_pct": 1.0}),
    )


def test_status_note_shows_distance_to_trigger():
    mgr = BotManager()
    # price 1% below prior close → right at the buy trigger
    note = mgr._status_note(_dca_bot(), "SPY", price=99.0, reference_price=100.0)
    assert "SPY" in note and "-1.00%" in note and "buys at -1.0%" in note


def test_status_note_generic_for_other_strategies():
    mgr = BotManager()
    bot = Bot(user_id=1, name="x",
              config=BotConfig(strategy=StrategyKind.breakout, symbols=["AAPL"], params={}))
    note = mgr._status_note(bot, "AAPL", price=210.0, reference_price=None)
    assert "AAPL" in note and "breakout" in note


def _capture_emits(monkeypatch):
    emitted = []

    async def fake_emit(bot, kind, detail):
        emitted.append((kind, detail))

    monkeypatch.setattr(executor_real, "_emit", fake_emit)
    return emitted


def test_watchdog_warns_on_stale_then_recovers(monkeypatch):
    bot = _dca_bot()
    mgr = BotManager()
    emitted = _capture_emits(monkeypatch)

    stale_ts = (datetime.now(timezone.utc) - timedelta(seconds=400)).isoformat(timespec="seconds")

    async def stale(ids):
        return {bot.id: {"ts": stale_ts, "note": "x"}}

    monkeypatch.setattr(health, "read_many", stale)
    asyncio.run(mgr._watchdog([bot]))
    assert any(d.get("action") == "heartbeat_stale" for _, d in emitted)
    assert bot.id in mgr._stale_warned

    # Second pass while still stale → no duplicate warning (one per episode).
    emitted.clear()
    asyncio.run(mgr._watchdog([bot]))
    assert emitted == []

    # Heartbeat resumes → a single recovery note.
    async def fresh(ids):
        return {bot.id: {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds")}}

    monkeypatch.setattr(health, "read_many", fresh)
    asyncio.run(mgr._watchdog([bot]))
    assert any(d.get("action") == "heartbeat_recovered" for _, d in emitted)
    assert bot.id not in mgr._stale_warned


def test_watchdog_warmup_grace_for_missing_heartbeat(monkeypatch):
    bot = _dca_bot()
    mgr = BotManager()
    emitted = _capture_emits(monkeypatch)

    async def none(ids):
        return {}

    monkeypatch.setattr(health, "read_many", none)

    # First sight: no heartbeat yet, but inside the warmup window → stay quiet.
    asyncio.run(mgr._watchdog([bot]))
    assert emitted == []

    # Pretend the bot has been active (snapshotless) past the warmup window.
    mgr._watch_since[bot.id] = time.monotonic() - 1000
    asyncio.run(mgr._watchdog([bot]))
    assert any(d.get("action") == "heartbeat_stale" for _, d in emitted)
