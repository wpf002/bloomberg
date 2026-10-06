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

    async def get_spin_offs(self, start, end):
        return []

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


# ── Wilder smoothing matches a step-by-step reference ──────────────────────

def _wilder(values, n=14):
    """Reference RMA: SMA seed over the first n values, then the recursion.
    Same definition as TradingView's ta.rma."""
    if len(values) < n:
        return None
    avg = sum(values[:n]) / n
    for v in values[n:]:
        avg = (avg * (n - 1) + v) / n
    return avg


def _reference_rsi_atr(bars):
    gains, losses, trs = [], [], []
    for prev, cur in zip(bars, bars[1:]):
        pc = prev[3]
        o, h, l, c = cur
        gains.append(max(c - pc, 0.0))
        losses.append(max(pc - c, 0.0))
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    g, lo, atr = _wilder(gains), _wilder(losses), _wilder(trs)
    rsi = 100.0 if lo == 0 else 100.0 - 100.0 / (1.0 + g / lo)
    return rsi, atr / bars[-1][3] * 100.0


@pytest.mark.parametrize("n_days", [61, 120, 300])
def test_rsi_and_atr_match_wilder_recursion(n_days):
    con = duckdb.connect(":memory:")
    con.execute(
        """CREATE TABLE bars(symbol TEXT, timestamp TIMESTAMP, open DOUBLE,
           high DOUBLE, low DOUBLE, close DOUBLE, volume BIGINT)"""
    )
    rng = random.Random(n_days)
    px, ohlc, rows = 100.0, [], []
    for i in range(n_days):
        o = px
        px *= 1 + rng.uniform(-0.04, 0.04)
        h, l = max(o, px) * (1 + rng.uniform(0, 0.01)), min(o, px) * (1 - rng.uniform(0, 0.01))
        ohlc.append((o, h, l, px))
        rows.append(("REF", dt.datetime(2025, 1, 1) + dt.timedelta(days=i), o, h, l, px, 1000))
    con.executemany("INSERT INTO bars VALUES (?,?,?,?,?,?,?)", rows)

    (row,) = _screen(con, [])
    want_rsi, want_atr = _reference_rsi_atr(ohlc)
    assert row["rsi14"] == pytest.approx(want_rsi, rel=1e-9)
    assert row["atr14_pct"] == pytest.approx(want_atr, rel=1e-9)


def test_wilder_rsi_is_less_extreme_than_simple_average():
    """The reason for the switch: a sustained decline read RSI ~4 under the
    simple average. Wilder carries older, calmer sessions forward."""
    con = duckdb.connect(":memory:")
    con.execute(
        """CREATE TABLE bars(symbol TEXT, timestamp TIMESTAMP, open DOUBLE,
           high DOUBLE, low DOUBLE, close DOUBLE, volume BIGINT)"""
    )
    rng = random.Random(3)
    px, rows = 150.0, []
    for i in range(200):
        # 186 sessions of chop, then 14 straight down days
        px *= (1 + rng.uniform(-0.01, 0.01)) if i < 186 else 0.98
        rows.append(("DOWN", dt.datetime(2025, 1, 1) + dt.timedelta(days=i), px, px * 1.005, px * 0.995, px, 1000))
    con.executemany("INSERT INTO bars VALUES (?,?,?,?,?,?,?)", rows)
    (row,) = _screen(con, [])
    assert 0.0 < row["rsi14"] < 30.0      # still flags oversold
    assert row["rsi14"] > 5.0             # but not the simple-average extreme of ~0


# ── spin-off adjustment ────────────────────────────────────────────────────

def _bars_table(rows):
    con = duckdb.connect(":memory:")
    con.execute(
        """CREATE TABLE bars_next(symbol TEXT, timestamp TIMESTAMP, open DOUBLE,
           high DOUBLE, low DOUBLE, close DOUBLE, volume BIGINT)"""
    )
    con.executemany("INSERT INTO bars_next VALUES (?,?,?,?,?,?,?)", rows)
    return con


def _day(i):
    return dt.datetime(2026, 9, 1) + dt.timedelta(days=i)


def test_spin_off_removes_the_cliff():
    """Parent trades 100 then 20 after spinning off a child worth 80, 1:1.
    f = 20 / (20 + 80) = 0.2, so pre-ex parent bars scale to 20."""
    from backend.core.sql_engine import _adjust_spin_offs

    rows = [("PAR", _day(i), 100, 101, 99, 100, 5000) for i in range(10)]
    rows += [("PAR", _day(i), 20, 20.2, 19.8, 20, 5000) for i in range(10, 20)]
    rows += [("KID", _day(i), 80, 81, 79, 80, 3000) for i in range(10, 20)]
    con = _bars_table(rows)

    stats = _adjust_spin_offs(con, [{"parent": "PAR", "child": "KID", "ratio": 1.0,
                                     "ex_date": _day(10).date().isoformat()}])
    assert stats == {"applied": 1, "skipped": 0}
    closes = [r[0] for r in con.execute(
        "SELECT close FROM bars_next WHERE symbol='PAR' ORDER BY timestamp").fetchall()]
    assert closes[9] == pytest.approx(20.0)   # day before ex, now continuous
    assert closes[10] == pytest.approx(20.0)  # ex-date untouched
    worst = min(b / a - 1 for a, b in zip(closes, closes[1:]))
    assert worst > -0.01, "cliff should be gone"


def test_spin_off_leaves_volume_and_child_alone():
    from backend.core.sql_engine import _adjust_spin_offs

    rows = [("PAR", _day(i), 100, 100, 100, 100, 5000) for i in range(5)]
    rows += [("PAR", _day(i), 50, 50, 50, 50, 5000) for i in range(5, 10)]
    rows += [("KID", _day(i), 50, 50, 50, 50, 3000) for i in range(5, 10)]
    con = _bars_table(rows)
    _adjust_spin_offs(con, [{"parent": "PAR", "child": "KID", "ratio": 1.0,
                             "ex_date": _day(5).date().isoformat()}])
    vols = {r[0] for r in con.execute("SELECT volume FROM bars_next WHERE symbol='PAR'").fetchall()}
    assert vols == {5000}
    kid = {r[0] for r in con.execute("SELECT close FROM bars_next WHERE symbol='KID'").fetchall()}
    assert kid == {50.0}


def test_spin_off_ratio_scales_child_value():
    """2 child shares per parent share at 10 each = 20 distributed;
    parent 80 after, so f = 80 / (80 + 20) = 0.8."""
    from backend.core.sql_engine import _adjust_spin_offs

    rows = [("PAR", _day(i), 100, 100, 100, 100, 1) for i in range(3)]
    rows += [("PAR", _day(i), 80, 80, 80, 80, 1) for i in range(3, 6)]
    rows += [("KID", _day(i), 10, 10, 10, 10, 1) for i in range(3, 6)]
    con = _bars_table(rows)
    _adjust_spin_offs(con, [{"parent": "PAR", "child": "KID", "ratio": 2.0,
                             "ex_date": _day(3).date().isoformat()}])
    first = con.execute("SELECT close FROM bars_next WHERE symbol='PAR' ORDER BY timestamp LIMIT 1").fetchone()[0]
    assert first == pytest.approx(80.0)


def test_spin_off_skipped_when_child_not_trading():
    """Escrow / CVR children (CUSIP-style symbols) have no bars: skip, don't guess."""
    from backend.core.sql_engine import _adjust_spin_offs

    rows = [("PAR", _day(i), 100, 100, 100, 100, 1) for i in range(6)]
    con = _bars_table(rows)
    stats = _adjust_spin_offs(con, [{"parent": "PAR", "child": "494ESC015", "ratio": 0.07,
                                     "ex_date": _day(3).date().isoformat()}])
    assert stats == {"applied": 0, "skipped": 1}
    assert {r[0] for r in con.execute("SELECT close FROM bars_next").fetchall()} == {100.0}


def test_two_spin_offs_on_one_parent_compose():
    """Factors are computed before any are applied, so the earlier spin-off's
    factor isn't skewed by the later one's adjustment."""
    from backend.core.sql_engine import _adjust_spin_offs

    # 100 -> (spin A worth 50) -> 50 -> (spin B worth 25) -> 25
    rows = [("PAR", _day(i), 100, 100, 100, 100, 1) for i in range(0, 3)]
    rows += [("PAR", _day(i), 50, 50, 50, 50, 1) for i in range(3, 6)]
    rows += [("PAR", _day(i), 25, 25, 25, 25, 1) for i in range(6, 9)]
    rows += [("KA", _day(i), 50, 50, 50, 50, 1) for i in range(3, 9)]
    rows += [("KB", _day(i), 25, 25, 25, 25, 1) for i in range(6, 9)]
    con = _bars_table(rows)
    stats = _adjust_spin_offs(con, [
        {"parent": "PAR", "child": "KB", "ratio": 1.0, "ex_date": _day(6).date().isoformat()},
        {"parent": "PAR", "child": "KA", "ratio": 1.0, "ex_date": _day(3).date().isoformat()},
    ])
    assert stats["applied"] == 2
    closes = [r[0] for r in con.execute(
        "SELECT close FROM bars_next WHERE symbol='PAR' ORDER BY timestamp").fetchall()]
    # Each spin halves the parent; fully adjusted, the series is flat at 25.
    assert closes == pytest.approx([25.0] * 9)
