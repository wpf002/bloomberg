"""Pytest coverage for backend/data/normalizer.py.

Run from repo root:
    pytest tests/test_normalizer.py -v
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend.data.normalizer import NormalizedRecord, Normalizer, get_normalizer


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── schema validation ───────────────────────────────────────────────────


def test_normalized_record_schema_basic():
    rec = NormalizedRecord(
        source="alpaca",
        symbol="AAPL",
        series_id="price",
        timestamp=_now(),
        value=150.25,
        unit="USD",
    )
    assert rec.source == "alpaca"
    assert rec.symbol == "AAPL"
    assert rec.value == pytest.approx(150.25)
    assert rec.tags == {}
    assert rec.ingested_at is not None


def test_normalize_uppercases_symbol():
    n = Normalizer()
    rec = n.normalize(source="alpaca", symbol="aapl", series_id="price", value=10)
    assert rec.symbol == "AAPL"


def test_normalize_accepts_int_value_and_casts_float():
    n = Normalizer()
    rec = n.normalize(source="x", symbol="y", series_id="z", value=42)
    assert isinstance(rec.value, float)
    assert rec.value == 42.0


def test_normalize_allows_none_value_for_marker_records():
    n = Normalizer()
    rec = n.normalize(source="sec", symbol="AAPL", series_id="filing:10-K", value=None)
    assert rec.value is None


# ── malformed input handling ────────────────────────────────────────────


def test_normalize_rejects_non_numeric_string():
    n = Normalizer()
    with pytest.raises(ValueError):
        n.normalize(source="x", symbol="y", series_id="z", value="not-a-number")


def test_normalize_many_skips_bad_records():
    n = Normalizer()
    out = n.normalize_many(
        [
            {"source": "a", "symbol": "AAPL", "series_id": "price", "value": 1.0},
            # malformed: value is a non-numeric string
            {"source": "a", "symbol": "AAPL", "series_id": "price", "value": "garbage"},
            {"source": "a", "symbol": "AAPL", "series_id": "price", "value": 2.0},
        ]
    )
    assert len(out) == 2
    assert all(r.value is not None for r in out)


def test_normalize_many_handles_empty_iterable():
    n = Normalizer()
    assert n.normalize_many([]) == []


# ── multi-source deduplication ──────────────────────────────────────────


def test_deduplicate_keeps_earliest_ingested_per_key():
    n = Normalizer()
    ts = _now()
    earlier = NormalizedRecord(
        source="alpaca",
        symbol="AAPL",
        series_id="price",
        timestamp=ts,
        ingested_at=ts - timedelta(seconds=10),
        value=150.0,
    )
    later = NormalizedRecord(
        source="finnhub",
        symbol="AAPL",
        series_id="price",
        timestamp=ts,  # same timestamp = same data point
        ingested_at=ts,
        value=150.05,
    )
    out = n.deduplicate([later, earlier])
    assert len(out) == 1
    assert out[0].source == "alpaca"  # earliest ingestion wins


def test_deduplicate_keeps_distinct_timestamps():
    n = Normalizer()
    base_ts = _now()
    a = NormalizedRecord(
        source="a", symbol="X", series_id="p", timestamp=base_ts, value=1.0
    )
    b = NormalizedRecord(
        source="b",
        symbol="X",
        series_id="p",
        timestamp=base_ts + timedelta(seconds=1),
        value=2.0,
    )
    out = n.deduplicate([a, b])
    assert len(out) == 2


def test_deduplicate_keeps_distinct_series():
    n = Normalizer()
    ts = _now()
    out = n.deduplicate(
        [
            NormalizedRecord(source="a", symbol="X", series_id="price", timestamp=ts, value=1.0),
            NormalizedRecord(source="a", symbol="X", series_id="volume", timestamp=ts, value=1000.0),
        ]
    )
    assert len(out) == 2


# ── provenance ring buffer ──────────────────────────────────────────────


def test_recent_returns_records_for_symbol_only():
    n = Normalizer()
    n.normalize(source="x", symbol="AAPL", series_id="price", value=1.0)
    n.normalize(source="x", symbol="MSFT", series_id="price", value=2.0)
    out = n.recent("AAPL", limit=10)
    assert len(out) == 1
    assert out[0].symbol == "AAPL"


def test_recent_filters_by_series_id_when_given():
    n = Normalizer()
    n.normalize(source="x", symbol="AAPL", series_id="price", value=1.0)
    n.normalize(source="x", symbol="AAPL", series_id="close", value=2.0)
    out = n.recent("AAPL", series_id="close")
    assert len(out) == 1
    assert out[0].series_id == "close"


def test_recent_respects_limit():
    n = Normalizer()
    for i in range(20):
        n.normalize(source="x", symbol="AAPL", series_id="price", value=float(i))
    assert len(n.recent("AAPL", limit=5)) == 5


def test_ring_buffer_evicts_oldest():
    n = Normalizer(buffer_capacity=3)
    for i in range(5):
        n.normalize(source="x", symbol="AAPL", series_id="price", value=float(i))
    out = n.recent("AAPL", limit=100)
    assert len(out) == 3
    # values pushed last must survive
    surviving = sorted(r.value for r in out)
    assert surviving == [2.0, 3.0, 4.0]


# ── singleton ───────────────────────────────────────────────────────────


def test_get_normalizer_returns_same_instance():
    a = get_normalizer()
    b = get_normalizer()
    assert a is b
