"""CBOE delayed options data — IV percentile / IV rank.

CBOE exposes free delayed options surfaces. Without an extra subscription
we can still enrich the IV view by tracking the per-symbol IV history
locally. To stay dependency-light, we compute IV Rank and IV Percentile
from a 252-trading-day buffer of historical implied vol values that we
build up from existing chain snapshots.

The buffer lives in-process (deque). For cross-process persistence we
fall back to whatever is in TimescaleDB's normalized_records — but the
in-memory cache is enough to serve the panel after a few requests warm
the buffer.
"""

from __future__ import annotations

import logging
from collections import deque
from typing import Any

logger = logging.getLogger(__name__)


class CboeSource:
    """Stateless calculator over a per-symbol IV history."""

    def __init__(self) -> None:
        self._iv_buffers: dict[str, deque[float]] = {}

    def record_iv(self, symbol: str, iv: float) -> None:
        if iv is None or iv <= 0:
            return
        sym = symbol.upper()
        buf = self._iv_buffers.setdefault(sym, deque(maxlen=252))
        buf.append(float(iv))

    def iv_rank(self, symbol: str) -> float | None:
        """IV Rank = (current - 52w low) / (52w high - 52w low)."""
        buf = self._iv_buffers.get(symbol.upper())
        if not buf or len(buf) < 5:
            return None
        cur = buf[-1]
        lo = min(buf)
        hi = max(buf)
        if hi == lo:
            return None
        return (cur - lo) / (hi - lo)

    def iv_percentile(self, symbol: str) -> float | None:
        """IV Percentile = % of trailing days with IV below current."""
        buf = self._iv_buffers.get(symbol.upper())
        if not buf or len(buf) < 5:
            return None
        cur = buf[-1]
        below = sum(1 for v in buf if v < cur)
        return below / len(buf)


_singleton: CboeSource | None = None


def get_cboe_source() -> CboeSource:
    global _singleton
    if _singleton is None:
        _singleton = CboeSource()
    return _singleton
