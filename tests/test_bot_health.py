"""Bot heartbeat: snapshot store roundtrip + status-note formatting."""

import asyncio

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
