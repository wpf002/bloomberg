"""Screener filter compilation and metric SQL."""

from __future__ import annotations

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
