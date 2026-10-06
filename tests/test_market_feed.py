"""Feed selection for Alpaca equity data, and the fallbacks when the account
isn't entitled to what was asked for."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from backend.core import market_feed


@pytest.fixture(autouse=True)
def _reset():
    market_feed._reset_for_tests()
    yield
    market_feed._reset_for_tests()


NOW = datetime(2026, 10, 6, 15, 0, tzinfo=timezone.utc)


# ── bar routing ────────────────────────────────────────────────────────────

def test_daily_bars_use_sip_with_lag_on_free_plan():
    p = market_feed.bar_params("1Day", NOW)
    assert p["feed"] == "sip"
    assert p["end"] == "2026-10-06T14:44:00Z"  # 16 minutes back


def test_daily_bars_on_paid_plan_have_no_lag():
    market_feed._reset_for_tests(live="sip")
    assert market_feed.bar_params("1Day", NOW) == {"feed": "sip"}


@pytest.mark.parametrize("tf", ["1Min", "5Min", "15Min", "1Hour"])
def test_intraday_bars_follow_the_live_feed(tf):
    # A 16-minute-stale intraday chart is worse than a thin-volume live one.
    assert market_feed.bar_params(tf, NOW) == {"feed": "iex"}
    market_feed._reset_for_tests(live="sip")
    assert market_feed.bar_params(tf, NOW) == {"feed": "sip"}


@pytest.mark.parametrize("tf", ["1Week", "1Month"])
def test_longer_timeframes_count_as_historical(tf):
    assert market_feed.bar_params(tf, NOW)["feed"] == "sip"


# ── fallbacks ──────────────────────────────────────────────────────────────

def test_historical_downgrade_switches_once():
    assert market_feed.downgrade("403", timeframe="1Day") is True
    assert market_feed.bar_params("1Day", NOW) == {"feed": "iex"}
    assert market_feed.downgrade("403 again", timeframe="1Day") is False


def test_historical_downgrade_leaves_live_feed_alone():
    market_feed._reset_for_tests(live="sip")
    market_feed.downgrade("403", timeframe="1Day")
    assert market_feed.current() == "sip"


def test_live_downgrade_switches_once():
    market_feed._reset_for_tests(live="sip")
    assert market_feed.downgrade("409") is True
    assert market_feed.current() == "iex"
    assert market_feed.downgrade("409 again") is False


def test_live_downgrade_is_noop_when_already_iex():
    assert market_feed.downgrade("409") is False


def test_entitlement_error_detection():
    assert market_feed.is_entitlement_error(403, '{"message":"subscription does not permit querying recent SIP data"}')
    assert not market_feed.is_entitlement_error(403, "forbidden")
    assert not market_feed.is_entitlement_error(429, "subscription rate")


# ── stream error frames ────────────────────────────────────────────────────

def _streamer():
    from backend.core.streaming import AlpacaStreamer
    return AlpacaStreamer()


def test_stream_409_on_sip_downgrades_and_reconnects():
    market_feed._reset_for_tests(live="sip")
    s = _streamer()
    assert s._handle_upstream_error({"T": "error", "code": 409, "msg": "insufficient subscription"}) is True
    assert market_feed.current() == "iex"


def test_stream_405_is_logged_once_with_the_symbol_cap(caplog):
    s = _streamer()
    s._symbols = {f"S{i}" for i in range(35)}
    frame = {"T": "error", "code": 405, "msg": "symbol limit exceeded"}
    with caplog.at_level("WARNING"):
        assert s._handle_upstream_error(frame) is False
        assert s._handle_upstream_error(frame) is False
    hits = [r for r in caplog.records if "symbol limit exceeded" in r.getMessage()]
    assert len(hits) == 1, "repeat errors should not flood the log"
    assert "35 symbols" in hits[0].getMessage() and "at most 30" in hits[0].getMessage()


def test_error_frames_are_not_dispatched_as_quotes():
    s = _streamer()
    dispatched = []

    async def spy(m):
        dispatched.append(m)

    s._dispatch_quote_msg = spy
    reconnect = asyncio.run(s._handle_quote_frames([
        {"T": "error", "code": 405, "msg": "symbol limit exceeded"},
        {"T": "q", "S": "AAPL", "bp": 1, "ap": 2},
    ]))
    assert reconnect is False
    assert [m["T"] for m in dispatched] == ["q"]


# ── connection limit (406) during deploys ──────────────────────────────────

def test_stream_406_reconnects_and_logs_once(caplog):
    """The free plan allows one stream connection. During a deploy the old
    container holds it; the new one used to sit on the refused socket forever,
    so live quotes died after every deploy."""
    s = _streamer()
    frame = {"T": "error", "code": 406, "msg": "connection limit exceeded"}
    with caplog.at_level("WARNING"):
        assert s._handle_upstream_error(frame) is True
        assert s._handle_upstream_error(frame) is True
    hits = [r for r in caplog.records if "406" in r.getMessage()]
    assert len(hits) == 1


def test_backoff_resets_only_on_authenticated():
    s = _streamer()
    s._backoff = 16.0
    reconnect = asyncio.run(s._handle_quote_frames([{"T": "success", "msg": "connected"}]))
    assert reconnect is False and s._backoff == 16.0   # a socket isn't a session
    asyncio.run(s._handle_quote_frames([{"T": "success", "msg": "authenticated"}]))
    assert s._backoff == 1.0


# ── event-loop lag monitor ─────────────────────────────────────────────────

def _run_monitor(monkeypatch, body):
    """Run the monitor around `body`, recording its warnings directly.

    Not caplog: importing backend.main runs configure_logging(), which replaces
    the root handlers, pytest's capture handler included.
    """
    import backend.main as main

    monkeypatch.setattr(main, "LOOP_LAG_INTERVAL", 0.05)
    monkeypatch.setattr(main, "LOOP_LAG_WARN_SECONDS", 0.2)
    seen = []
    monkeypatch.setattr(main.logger, "warning", lambda msg, *a, **kw: seen.append((msg, kw.get("extra", {}))))

    async def scenario():
        monitor = asyncio.create_task(main._loop_lag_monitor())
        await body()
        monitor.cancel()
        try:
            await monitor
        except asyncio.CancelledError:
            pass

    asyncio.run(scenario())
    return [extra for msg, extra in seen if msg == "event loop blocked"]


def test_loop_lag_monitor_reports_a_blocked_loop(monkeypatch):
    import time

    async def body():
        await asyncio.sleep(0.1)
        time.sleep(0.5)          # block the loop the way a synchronous call would
        await asyncio.sleep(0.2)

    blocked = _run_monitor(monkeypatch, body)
    assert blocked, "a 0.5s block should be reported"
    assert blocked[0]["seconds"] >= 0.3


def test_loop_lag_monitor_quiet_when_idle(monkeypatch):
    async def body():
        await asyncio.sleep(0.4)

    assert _run_monitor(monkeypatch, body) == []
