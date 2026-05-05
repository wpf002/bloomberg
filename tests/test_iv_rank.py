"""V2.6 — IV Rank / IV Percentile math.

The CBOE source keeps a 252-day rolling buffer of implied vol values
per symbol. IV Rank scales the latest reading between the 52w low and
high; IV Percentile is the share of buffered days strictly below the
latest reading.
"""

from __future__ import annotations

import math

from backend.data.sources.cboe_source import CboeSource


def test_iv_rank_returns_none_until_enough_history():
    s = CboeSource()
    s.record_iv("AAPL", 0.30)
    assert s.iv_rank("AAPL") is None
    s.record_iv("AAPL", 0.32)
    s.record_iv("AAPL", 0.31)
    s.record_iv("AAPL", 0.33)
    assert s.iv_rank("AAPL") is None  # still <5 datapoints


def test_iv_rank_at_low_is_zero_at_high_is_one():
    s = CboeSource()
    for v in [0.10, 0.20, 0.30, 0.40, 0.50]:
        s.record_iv("MSFT", v)
    # current is 0.50 (the high) → rank = 1.0
    assert math.isclose(s.iv_rank("MSFT"), 1.0)
    # push the low last → rank = 0.0
    s2 = CboeSource()
    for v in [0.50, 0.40, 0.30, 0.20, 0.10]:
        s2.record_iv("NVDA", v)
    assert math.isclose(s2.iv_rank("NVDA"), 0.0)


def test_iv_rank_midpoint_when_current_is_median():
    s = CboeSource()
    for v in [0.10, 0.20, 0.30, 0.40, 0.50, 0.30]:
        s.record_iv("AAPL", v)
    # current 0.30, low 0.10, high 0.50 → (0.30-0.10)/(0.50-0.10) = 0.5
    assert math.isclose(s.iv_rank("AAPL"), 0.5)


def test_iv_rank_returns_none_when_buffer_is_flat():
    s = CboeSource()
    for _ in range(10):
        s.record_iv("FLAT", 0.30)
    assert s.iv_rank("FLAT") is None  # high == low → undefined rank


def test_iv_percentile_counts_strict_below():
    s = CboeSource()
    for v in [0.10, 0.20, 0.30, 0.40, 0.50]:
        s.record_iv("AAPL", v)
    # current 0.50, 4 of 5 strictly below
    assert math.isclose(s.iv_percentile("AAPL"), 4 / 5)


def test_iv_percentile_zero_when_current_is_lowest():
    s = CboeSource()
    for v in [0.50, 0.40, 0.30, 0.20, 0.10]:
        s.record_iv("AAPL", v)
    assert math.isclose(s.iv_percentile("AAPL"), 0.0)


def test_record_iv_ignores_invalid_values():
    s = CboeSource()
    s.record_iv("AAPL", 0.0)
    s.record_iv("AAPL", -1.0)
    s.record_iv("AAPL", None)
    assert s.iv_rank("AAPL") is None
    assert s.iv_percentile("AAPL") is None


def test_buffer_capped_at_252_entries():
    s = CboeSource()
    for i in range(300):
        s.record_iv("AAPL", 0.10 + i * 0.001)
    assert len(s._iv_buffers["AAPL"]) == 252
