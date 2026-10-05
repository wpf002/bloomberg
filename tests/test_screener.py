"""Screener filter compilation and metric SQL."""

from __future__ import annotations

import asyncio
import datetime as dt
import random

import duckdb
import pytest

from backend.core.screener import METRICS_SQL, FIELD_KEYS, build_query, compile_filters


# ── filter compilation ─────────────────────────────────────────────────────

def test_compile_simple_filter():
    pred, params = compile_filters([{"field": "price", "op": "gt", "value": 10}])
    assert pred == '"price" > ?'
    assert params == [10.0]


def test_compile_between():
    pred, params = compile_filters([{"field": "rsi14", "op": "between", "min": 30, "max": 70}])
    assert pred == '"rsi14" BETWEEN ? AND ?'
    assert params == [30.0, 70.0]


def test_compile_multiple_filters_are_anded():
    pred, params = compile_filters([
        {"field": "price", "op": "gte", "value": 5},
        {"field": "rel_volume", "op": "gt", "value": 2},
    ])
    assert pred == '"price" >= ? AND "rel_volume" > ?'
    assert params == [5.0, 2.0]


def test_empty_filters_match_everything():
    pred, params = compile_filters([])
    assert pred == "TRUE"
    assert params == []


def test_unknown_field_rejected():
    # The guard that keeps user text out of the SQL string.
    with pytest.raises(ValueError, match="unknown field"):
        compile_filters([{"field": "close); DROP TABLE bars;--", "op": "gt", "value": 1}])


def test_unknown_op_rejected():
    with pytest.raises(ValueError, match="unknown op"):
        compile_filters([{"field": "price", "op": "regex", "value": 1}])


def test_between_requires_both_bounds():
    with pytest.raises(ValueError, match="between needs both"):
        compile_filters([{"field": "price", "op": "between", "min": 1}])


def test_missing_value_rejected():
    with pytest.raises(ValueError, match="needs a value"):
        compile_filters([{"field": "price", "op": "gt"}])


def test_bad_sort_rejected():
    with pytest.raises(ValueError, match="cannot sort by"):
        build_query([], sort="price; DROP TABLE bars")


def test_limit_is_clamped():
    sql, _ = build_query([], limit=99999)
    assert "LIMIT 500" in sql


def test_query_reads_the_materialised_table():
    sql, _ = build_query([])
    assert "screener_metrics" in sql


# ── metric SQL against real DuckDB ─────────────────────────────────────────

def _con_with_bars(n_days: int = 300):
    con = duckdb.connect(":memory:")
    con.execute(
        """CREATE TABLE bars(symbol TEXT, timestamp TIMESTAMP, open DOUBLE,
           high DOUBLE, low DOUBLE, close DOUBLE, volume BIGINT)"""
    )
    random.seed(11)
    rows = []
    for sym, base in (("AAA", 100.0), ("BBB", 50.0), ("CCC", 10.0)):
        px = base
        for i in range(n_days):
            px *= 1 + random.uniform(-0.03, 0.032)
            rows.append((
                sym, dt.datetime(2025, 1, 1) + dt.timedelta(days=i),
                px * 0.995, px * 1.02, px * 0.98, px,
                int(1e6 * random.uniform(0.5, 2)),
            ))
    con.executemany("INSERT INTO bars VALUES (?,?,?,?,?,?,?)", rows)
    return con


def _materialise(con, min_bars: int = 60):
    """Mirror SqlEngine._rebuild_metrics so tests exercise the shipped SQL."""
    con.execute("DROP TABLE IF EXISTS screener_metrics")
    con.execute(f"CREATE TABLE screener_metrics AS {METRICS_SQL.format(min_bars=min_bars, where='')}")
    return con


def _screen(con, filters, **kw):
    _materialise(con)
    sql, params = build_query(filters, **kw)
    cur = con.execute(sql, params)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def test_every_declared_field_is_a_column():
    rows = _screen(_con_with_bars(), [])
    assert rows
    missing = FIELD_KEYS - set(rows[0])
    assert not missing, f"FIELDS declares columns the SQL doesn't produce: {missing}"


def test_one_row_per_symbol():
    rows = _screen(_con_with_bars(), [])
    symbols = [r["symbol"] for r in rows]
    assert sorted(symbols) == ["AAA", "BBB", "CCC"]
    assert len(symbols) == len(set(symbols))


def test_rsi_within_bounds():
    for r in _screen(_con_with_bars(), []):
        assert 0.0 <= r["rsi14"] <= 100.0


def test_pct_off_52w_high_is_not_positive():
    # The latest close can equal the 52w high but never exceed it.
    for r in _screen(_con_with_bars(), []):
        assert r["pct_off_52w_high"] <= 0.01


def test_filter_actually_narrows():
    con = _con_with_bars()
    everything = _screen(con, [])
    cutoff = sorted(r["price"] for r in everything)[-1]
    filtered = _screen(con, [{"field": "price", "op": "gte", "value": cutoff}])
    assert len(filtered) == 1
    assert len(everything) == 3


def test_sort_desc_orders_rows():
    rows = _screen(_con_with_bars(), [], sort="price", desc=True)
    prices = [r["price"] for r in rows]
    assert prices == sorted(prices, reverse=True)


def test_min_bars_excludes_short_history():
    # A symbol with 10 sessions has no meaningful SMA200 or 52w range.
    con = _con_with_bars()
    con.executemany(
        "INSERT INTO bars VALUES (?,?,?,?,?,?,?)",
        [("NEW", dt.datetime(2026, 1, 1) + dt.timedelta(days=i), 5, 5, 5, 5, 1000)
         for i in range(10)],
    )
    symbols = {r["symbol"] for r in _screen(con, [])}
    assert "NEW" not in symbols


def test_empty_bars_table_returns_nothing():
    con = duckdb.connect(":memory:")
    con.execute(
        """CREATE TABLE bars(symbol TEXT, timestamp TIMESTAMP, open DOUBLE,
           high DOUBLE, low DOUBLE, close DOUBLE, volume BIGINT)"""
    )
    assert _screen(con, []) == []


# ── refresh schedule ───────────────────────────────────────────────────────

def test_refresh_schedule_skips_weekends(monkeypatch):
    """A Friday-evening tick must land on Monday, not Saturday."""
    import backend.main as main
    from datetime import datetime, timezone

    class FrozenDT(datetime):
        @classmethod
        def now(cls, tz=None):
            # Fri 2026-10-02 23:00 UTC — past that day's 22:00 target.
            return datetime(2026, 10, 2, 23, 0, tzinfo=tz or timezone.utc)

    monkeypatch.setattr(main, "datetime", FrozenDT)
    secs = main._seconds_until_universe_refresh()
    landing = FrozenDT.now(timezone.utc).timestamp() + secs
    landed = datetime.fromtimestamp(landing, tz=timezone.utc)
    assert landed.weekday() == 0, f"expected Monday, got {landed:%A}"
    assert landed.hour == 22


def test_refresh_schedule_same_day_when_before_target(monkeypatch):
    import backend.main as main
    from datetime import datetime, timezone

    class FrozenDT(datetime):
        @classmethod
        def now(cls, tz=None):
            # Tue 2026-10-06 09:00 UTC — target is later the same day.
            return datetime(2026, 10, 6, 9, 0, tzinfo=tz or timezone.utc)

    monkeypatch.setattr(main, "datetime", FrozenDT)
    assert main._seconds_until_universe_refresh() == 13 * 3600


def test_refresh_schedule_is_always_positive(monkeypatch):
    import backend.main as main
    from datetime import datetime, timedelta, timezone

    base = datetime(2026, 10, 1, tzinfo=timezone.utc)
    for hours in range(0, 24 * 9):
        moment = base + timedelta(hours=hours)

        class FrozenDT(datetime):
            @classmethod
            def now(cls, tz=None, _m=moment):
                return _m

        monkeypatch.setattr(main, "datetime", FrozenDT)
        secs = main._seconds_until_universe_refresh()
        assert 0 < secs <= 4 * 24 * 3600


# ── cold-start seed ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cold_start_seeds_when_universe_empty(monkeypatch):
    import backend.main as main

    calls = []

    async def fake_refresh(limit=None):
        calls.append("refresh")
        return 123

    async def no_sleep(_):
        raise asyncio.CancelledError  # stop after the seed block

    monkeypatch.setattr(main.sql_engine, "universe_size", lambda: 0)
    monkeypatch.setattr(main.sql_engine, "refresh_universe", fake_refresh)
    monkeypatch.setattr(main.leader_lock, "is_leader", lambda: True)
    monkeypatch.setattr(main.settings, "screener_refresh_enabled", True)

    sleeps = {"n": 0}

    async def seed_then_stop(_secs):
        sleeps["n"] += 1
        if sleeps["n"] > 1:
            raise asyncio.CancelledError
        return None

    monkeypatch.setattr(main.asyncio, "sleep", seed_then_stop)
    with pytest.raises(asyncio.CancelledError):
        await main._screener_universe_cron()
    assert calls == ["refresh"]


@pytest.mark.asyncio
async def test_cold_start_skips_when_universe_populated(monkeypatch):
    import backend.main as main

    calls = []

    async def fake_refresh(limit=None):
        calls.append("refresh")
        return 0

    monkeypatch.setattr(main.sql_engine, "universe_size", lambda: 9000)
    monkeypatch.setattr(main.sql_engine, "refresh_universe", fake_refresh)
    monkeypatch.setattr(main.leader_lock, "is_leader", lambda: True)
    monkeypatch.setattr(main.settings, "screener_refresh_enabled", True)

    sleeps = {"n": 0}

    async def seed_then_stop(_secs):
        sleeps["n"] += 1
        if sleeps["n"] > 1:
            raise asyncio.CancelledError
        return None

    monkeypatch.setattr(main.asyncio, "sleep", seed_then_stop)
    with pytest.raises(asyncio.CancelledError):
        await main._screener_universe_cron()
    assert calls == []


@pytest.mark.asyncio
async def test_cold_start_skips_when_not_leader(monkeypatch):
    import backend.main as main

    calls = []

    async def fake_refresh(limit=None):
        calls.append("refresh")
        return 0

    monkeypatch.setattr(main.sql_engine, "universe_size", lambda: 0)
    monkeypatch.setattr(main.sql_engine, "refresh_universe", fake_refresh)
    monkeypatch.setattr(main.leader_lock, "is_leader", lambda: False)
    monkeypatch.setattr(main.settings, "screener_refresh_enabled", True)

    sleeps = {"n": 0}

    async def seed_then_stop(_secs):
        sleeps["n"] += 1
        if sleeps["n"] > 1:
            raise asyncio.CancelledError
        return None

    monkeypatch.setattr(main.asyncio, "sleep", seed_then_stop)
    with pytest.raises(asyncio.CancelledError):
        await main._screener_universe_cron()
    assert calls == []


@pytest.mark.asyncio
async def test_cron_disabled_returns_immediately(monkeypatch):
    import backend.main as main

    monkeypatch.setattr(main.settings, "screener_refresh_enabled", False)
    await main._screener_universe_cron()  # must return, not hang


# ── refresh concurrency (regressions from the first production deploy) ─────

class _FakeAlpaca:
    """Stands in for AlpacaSource: N symbols x 300 daily bars each."""

    # A real multi-symbol request always yields to the loop; a fake that never
    # awaits would hide on-loop blocking, so default to a small delay.
    def __init__(self, n_symbols: int = 1200, delay: float = 0.01):
        self.n = n_symbols
        self.delay = delay

    def credentials_configured(self):
        return True

    async def list_active_assets(self):
        return [{"symbol": f"S{i:04d}", "tradable": True} for i in range(self.n)]

    async def get_bars_multi(self, symbols, *, days=400, chunk=200, raw=False):
        if self.delay:
            await asyncio.sleep(self.delay)
        start = dt.datetime(2025, 1, 1)
        out = {}
        for k, sym in enumerate(symbols):
            px = 10.0 + k % 50
            out[sym] = [
                (start + dt.timedelta(days=d), px, px * 1.01, px * 0.99, px * (1 + (d % 7 - 3) / 300), 100_000 + d)
                for d in range(300)
            ]
        return out


@pytest.fixture
def fresh_engine(monkeypatch):
    """A SqlEngine on its own in-memory database, wired to the fake source."""
    from backend.core import sql_engine as se

    monkeypatch.setattr(se.settings, "duckdb_path", "")
    eng = se.SqlEngine()
    monkeypatch.setattr(se, "get_alpaca_source", lambda: _FakeAlpaca())
    return eng


@pytest.mark.asyncio
async def test_refresh_builds_bars_and_metrics(fresh_engine):
    rows = await fresh_engine.refresh_universe()
    assert rows == 1200 * 300
    assert fresh_engine.universe_size() == 1200
    leftover = fresh_engine.con.execute(
        "SELECT COUNT(*) FROM information_schema.tables "
        "WHERE table_name IN ('bars_next', 'screener_metrics_next')"
    ).fetchone()[0]
    assert leftover == 0, "staging tables should be swapped away"


@pytest.mark.asyncio
async def test_refresh_writes_run_off_the_event_loop(fresh_engine, monkeypatch):
    """DuckDB writes must run on a worker thread. In production they ran on the
    loop and stalled HTTP and the bot tick loop for 30+ minutes.

    Asserts thread identity rather than loop lag: with the bulk insert, on-loop
    and off-loop lag differ by only a few hundred ms at test sizes, which is
    too close to be a reliable signal on a slow machine.
    """
    import threading
    from backend.core import sql_engine as se

    loop_thread = threading.get_ident()
    seen: dict[str, set[int]] = {"insert": set(), "metrics": set()}

    real_insert = se._insert_frame

    def spy_insert(cur, frame):
        seen["insert"].add(threading.get_ident())
        return real_insert(cur, frame)

    real_rebuild = fresh_engine._rebuild_metrics

    def spy_rebuild(cur=None):
        seen["metrics"].add(threading.get_ident())
        return real_rebuild(cur)

    monkeypatch.setattr(se, "_insert_frame", spy_insert)
    monkeypatch.setattr(fresh_engine, "_rebuild_metrics", spy_rebuild)

    await fresh_engine.refresh_universe()

    assert seen["insert"], "no bulk inserts recorded"
    assert seen["metrics"], "metrics rebuild never ran"
    assert loop_thread not in seen["insert"], "bar inserts ran on the event loop thread"
    assert loop_thread not in seen["metrics"], "metrics rebuild ran on the event loop thread"


@pytest.mark.asyncio
async def test_concurrent_refresh_is_refused(fresh_engine, monkeypatch):
    from backend.core import sql_engine as se

    monkeypatch.setattr(se, "get_alpaca_source", lambda: _FakeAlpaca(n_symbols=600, delay=0.2))
    first = asyncio.create_task(fresh_engine.refresh_universe())
    await asyncio.sleep(0.05)
    with pytest.raises(se.RefreshInProgress):
        await fresh_engine.refresh_universe()
    assert await first == 600 * 300


@pytest.mark.asyncio
async def test_screen_reads_previous_metrics_during_refresh(fresh_engine, monkeypatch):
    """A screen mid-refresh must see the old universe, never a dropped table."""
    from backend.core import sql_engine as se

    await fresh_engine.refresh_universe()
    before = fresh_engine.universe_size()

    monkeypatch.setattr(se, "get_alpaca_source", lambda: _FakeAlpaca(n_symbols=600, delay=0.2))
    second = asyncio.create_task(fresh_engine.refresh_universe())
    await asyncio.sleep(0.05)
    sql, params = build_query([], limit=5)
    rows = await fresh_engine.run_screen(sql, params)
    assert rows, "screen returned nothing mid-refresh"
    assert fresh_engine.universe_size() == before
    await second
    assert fresh_engine.universe_size() == 600
