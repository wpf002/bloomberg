"""Technical stock screener over the DuckDB `bars` table.

Every metric here is derived from OHLCV, so the screener runs across the whole
Alpaca equity universe without a fundamentals feed — no per-symbol API call and
no paid data tier. Fundamental filters (P/E, margins) need a different ingest
and are deliberately out of scope; see FIELDS for what exists today.

The universe is ingested by `screener_universe.refresh()` into the same `bars`
table the SQL workbench reads, so a filter here and a hand-written query there
see identical data.

Filters arrive as structured {field, op, value} triples and are compiled to
parameterised SQL. User text never reaches the query string.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Literal

logger = logging.getLogger(__name__)

Op = Literal["gt", "gte", "lt", "lte", "eq", "between"]

_OPS: dict[str, str] = {
    "gt": ">", "gte": ">=", "lt": "<", "lte": "<=", "eq": "=",
}


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    unit: str          # "usd" | "pct" | "x" | "num"
    help: str


# Every entry maps to a column produced by METRICS_SQL below. Adding a field
# means adding it in both places.
FIELDS: tuple[Field, ...] = (
    Field("price", "Price", "usd", "Latest close"),
    Field("change_pct", "Change %", "pct", "Latest close vs prior close"),
    Field("volume", "Volume", "num", "Latest session volume"),
    Field("avg_volume_30d", "Avg volume 30d", "num", "Mean volume over 30 sessions"),
    Field("rel_volume", "Relative volume", "x", "Latest volume / 30d average"),
    Field("dollar_volume", "Dollar volume", "usd", "Close x volume, latest session"),
    Field("pct_off_52w_high", "% off 52w high", "pct", "Discount to the 52-week high"),
    Field("pct_above_52w_low", "% above 52w low", "pct", "Premium to the 52-week low"),
    Field("sma20", "SMA 20", "usd", "20-session simple moving average"),
    Field("sma50", "SMA 50", "usd", "50-session simple moving average"),
    Field("sma200", "SMA 200", "usd", "200-session simple moving average"),
    Field("price_vs_sma50", "Price vs SMA50 %", "pct", "Close relative to its 50-day average"),
    Field("price_vs_sma200", "Price vs SMA200 %", "pct", "Close relative to its 200-day average"),
    Field("rsi14", "RSI 14", "num", "Wilder RSI, 14 sessions (matches charting tools)"),
    Field("gap_pct", "Gap %", "pct", "Latest open vs prior close"),
    Field("atr14_pct", "ATR 14 %", "pct", "Wilder ATR as a share of price"),
    Field("ret_1w", "Return 1w", "pct", "5-session return"),
    Field("ret_1m", "Return 1m", "pct", "21-session return"),
    Field("ret_3m", "Return 3m", "pct", "63-session return"),
)

FIELD_KEYS = frozenset(f.key for f in FIELDS)

SORTABLE = FIELD_KEYS | {"symbol"}

# One pass over `bars` building every metric per symbol. Window functions do the
# work so there is no Python-side loop over the universe.
#
# RSI and ATR use Wilder's smoothing (RMA, alpha = 1/14), the same definition
# TradingView and most charting tools use, so the numbers here match what a
# trader sees elsewhere. A simple 14-session average reads far more extreme:
# CHTR showed 4.2 against roughly 15 on a chart. See `agg` for how the
# recursion is computed without a recursive window.
METRICS_SQL = """
WITH ordered AS (
    SELECT
        symbol, timestamp, open, high, low, close, volume,
        LAG(close) OVER w        AS prev_close,
        ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY timestamp DESC) AS rn_desc,
        AVG(close)  OVER (PARTITION BY symbol ORDER BY timestamp ROWS BETWEEN 19  PRECEDING AND CURRENT ROW) AS sma20,
        AVG(close)  OVER (PARTITION BY symbol ORDER BY timestamp ROWS BETWEEN 49  PRECEDING AND CURRENT ROW) AS sma50,
        AVG(close)  OVER (PARTITION BY symbol ORDER BY timestamp ROWS BETWEEN 199 PRECEDING AND CURRENT ROW) AS sma200,
        AVG(volume) OVER (PARTITION BY symbol ORDER BY timestamp ROWS BETWEEN 29  PRECEDING AND CURRENT ROW) AS avg_volume_30d,
        MAX(high)   OVER (PARTITION BY symbol ORDER BY timestamp ROWS BETWEEN 251 PRECEDING AND CURRENT ROW) AS high_52w,
        MIN(low)    OVER (PARTITION BY symbol ORDER BY timestamp ROWS BETWEEN 251 PRECEDING AND CURRENT ROW) AS low_52w,
        LAG(close, 5)  OVER w AS close_5,
        LAG(close, 21) OVER w AS close_21,
        LAG(close, 63) OVER w AS close_63,
        COUNT(*) OVER (PARTITION BY symbol) AS bar_count
    FROM bars
    {where}
    WINDOW w AS (PARTITION BY symbol ORDER BY timestamp)
),
moves AS (
    SELECT
        symbol,
        GREATEST(close - prev_close, 0) AS gain,
        GREATEST(prev_close - close, 0) AS loss,
        GREATEST(high - low, ABS(high - prev_close), ABS(low - prev_close)) AS tr,
        ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY timestamp) AS rn,
        COUNT(*)     OVER (PARTITION BY symbol)                    AS n
    FROM ordered
    WHERE prev_close IS NOT NULL
),
agg AS (
    -- Wilder's recursion A[t] = (1-a)*A[t-1] + a*x[t], seeded with the simple
    -- mean of the first 14 values, unrolls to
    --     A[T] = (1-a)^(T-14) * mean(x[1..14]) + a * SUM over t>14 of (1-a)^(T-t) * x[t]
    -- which is an ordinary aggregate. Exact, not an approximation.
    -- (No braces in this comment: METRICS_SQL goes through str.format.)
    SELECT
        symbol,
        CASE WHEN MAX(n) >= 14 THEN
            POW(13.0 / 14.0, MAX(n) - 14) * AVG(gain) FILTER (WHERE rn <= 14)
            + (1.0 / 14.0) * COALESCE(SUM(gain * POW(13.0 / 14.0, n - rn)) FILTER (WHERE rn > 14), 0)
        END AS avg_gain,
        CASE WHEN MAX(n) >= 14 THEN
            POW(13.0 / 14.0, MAX(n) - 14) * AVG(loss) FILTER (WHERE rn <= 14)
            + (1.0 / 14.0) * COALESCE(SUM(loss * POW(13.0 / 14.0, n - rn)) FILTER (WHERE rn > 14), 0)
        END AS avg_loss,
        CASE WHEN MAX(n) >= 14 THEN
            POW(13.0 / 14.0, MAX(n) - 14) * AVG(tr) FILTER (WHERE rn <= 14)
            + (1.0 / 14.0) * COALESCE(SUM(tr * POW(13.0 / 14.0, n - rn)) FILTER (WHERE rn > 14), 0)
        END AS atr14
    FROM moves
    GROUP BY symbol
)
SELECT
    o.symbol                                                   AS symbol,
    o.close                                                    AS price,
    CASE WHEN o.prev_close > 0
         THEN (o.close / o.prev_close - 1) * 100 END           AS change_pct,
    o.volume                                                   AS volume,
    o.avg_volume_30d                                           AS avg_volume_30d,
    CASE WHEN o.avg_volume_30d > 0
         THEN o.volume / o.avg_volume_30d END                  AS rel_volume,
    o.close * o.volume                                         AS dollar_volume,
    CASE WHEN o.high_52w > 0
         THEN (o.close / o.high_52w - 1) * 100 END             AS pct_off_52w_high,
    CASE WHEN o.low_52w > 0
         THEN (o.close / o.low_52w - 1) * 100 END              AS pct_above_52w_low,
    o.sma20                                                    AS sma20,
    o.sma50                                                    AS sma50,
    o.sma200                                                   AS sma200,
    CASE WHEN o.sma50 > 0
         THEN (o.close / o.sma50 - 1) * 100 END                AS price_vs_sma50,
    CASE WHEN o.sma200 > 0
         THEN (o.close / o.sma200 - 1) * 100 END               AS price_vs_sma200,
    CASE
        WHEN a.avg_loss IS NULL OR a.avg_gain IS NULL THEN NULL
        WHEN a.avg_loss = 0 THEN 100.0
        ELSE 100.0 - (100.0 / (1.0 + (a.avg_gain / a.avg_loss)))
    END                                                        AS rsi14,
    CASE WHEN o.prev_close > 0
         THEN (o.open / o.prev_close - 1) * 100 END            AS gap_pct,
    CASE WHEN o.close > 0
         THEN (a.atr14 / o.close) * 100 END                    AS atr14_pct,
    CASE WHEN o.close_5  > 0 THEN (o.close / o.close_5  - 1) * 100 END AS ret_1w,
    CASE WHEN o.close_21 > 0 THEN (o.close / o.close_21 - 1) * 100 END AS ret_1m,
    CASE WHEN o.close_63 > 0 THEN (o.close / o.close_63 - 1) * 100 END AS ret_3m,
    o.timestamp                                                AS as_of
FROM ordered o
LEFT JOIN agg a USING (symbol)
WHERE o.rn_desc = 1 AND o.bar_count >= {min_bars}
"""


def compile_filters(filters: list[dict[str, Any]]) -> tuple[str, list[Any]]:
    """Turn structured filters into a SQL predicate plus bound parameters.

    Raises ValueError on an unknown field or operator so a bad request fails
    with a 400 rather than silently returning the unfiltered universe.
    """
    clauses: list[str] = []
    params: list[Any] = []
    for f in filters or []:
        field = str(f.get("field") or "")
        op = str(f.get("op") or "")
        if field not in FIELD_KEYS:
            raise ValueError(f"unknown field: {field}")
        if op == "between":
            lo, hi = f.get("min"), f.get("max")
            if lo is None or hi is None:
                raise ValueError("between needs both min and max")
            clauses.append(f'"{field}" BETWEEN ? AND ?')
            params.extend([float(lo), float(hi)])
            continue
        if op not in _OPS:
            raise ValueError(f"unknown op: {op}")
        value = f.get("value")
        if value is None:
            raise ValueError(f"{field} {op} needs a value")
        clauses.append(f'"{field}" {_OPS[op]} ?')
        params.append(float(value))
    return (" AND ".join(clauses) if clauses else "TRUE"), params


def build_query(
    filters: list[dict[str, Any]],
    *,
    sort: str = "dollar_volume",
    desc: bool = True,
    limit: int = 100,
) -> tuple[str, list[Any]]:
    if sort not in SORTABLE:
        raise ValueError(f"cannot sort by: {sort}")
    limit = max(1, min(int(limit), 500))
    predicate, params = compile_filters(filters)
    # Read the table `SqlEngine._rebuild_metrics` materialises at refresh
    # time. `min_bars` is applied there, not here.
    sql = (
        f"SELECT * FROM screener_metrics WHERE {predicate} "
        f'ORDER BY "{sort}" {"DESC" if desc else "ASC"} NULLS LAST '
        f"LIMIT {limit}"
    )
    return sql, params
