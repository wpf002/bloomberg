"""Read-only DuckDB engine — our `BQL` equivalent.

Tables registered in-memory at startup:

  bars(symbol, timestamp, open, high, low, close, volume)
      Daily Alpaca bars for a curated symbol set.

  macro(series_id, observation_date, value)
      FRED macro series points.

  filings(symbol, accession_number, form_type, filed_at, primary_document, url)
      SEC EDGAR filings index for the same curated symbol set.

The route layer is read-only: only `SELECT` / `WITH` / `EXPLAIN` queries
are accepted, multiple statements are rejected at the parser layer, and
results are capped to `settings.sql_query_max_rows`. We run queries on a
worker thread so a runaway scan doesn't block the event loop.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any

import duckdb

from ..data.sources import FredSource, SecEdgarSource, get_alpaca_source
from .config import settings

logger = logging.getLogger(__name__)


WARMUP_SYMBOLS = ["AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "GOOGL", "META", "SPY", "QQQ", "TLT"]
WARMUP_MACRO = ["GDP", "CPIAUCSL", "UNRATE", "FEDFUNDS", "DGS10", "DGS2"]

_READONLY_LEADING = re.compile(r"^\s*(WITH|SELECT|EXPLAIN|PRAGMA|SHOW|DESCRIBE)\b", re.IGNORECASE)
_FORBIDDEN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|ATTACH|COPY|EXPORT|IMPORT|"
    r"TRUNCATE|REINDEX|CALL|VACUUM|LOAD|INSTALL)\b",
    re.IGNORECASE,
)


class SqlEngine:
    """Wraps a single in-memory DuckDB connection. All ingestion happens via
    Pandas DataFrames (DuckDB's native frame interop) — we lean on the
    versions of pandas / numpy already pinned for the rest of the backend.
    """

    def __init__(self) -> None:
        self.con = duckdb.connect(":memory:")
        self.con.execute(
            """
            CREATE TABLE IF NOT EXISTS bars (
                symbol TEXT,
                timestamp TIMESTAMP,
                open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE,
                volume BIGINT
            );
            CREATE TABLE IF NOT EXISTS macro (
                series_id TEXT,
                observation_date DATE,
                value DOUBLE
            );
            CREATE TABLE IF NOT EXISTS filings (
                symbol TEXT,
                accession_number TEXT,
                form_type TEXT,
                filed_at TIMESTAMP,
                primary_document TEXT,
                url TEXT
            );
            """
        )

    # ── ingestion ───────────────────────────────────────────────────────

    async def warm(self) -> None:
        """Pull a small starter dataset so the very first SELECT returns rows.
        Best-effort: any provider error is logged and skipped.
        """
        try:
            await self._warm_bars(WARMUP_SYMBOLS)
        except Exception as exc:
            logger.warning("sql warm bars failed: %s", exc)
        try:
            await self._warm_macro(WARMUP_MACRO)
        except Exception as exc:
            logger.warning("sql warm macro failed: %s", exc)
        try:
            await self._warm_filings(WARMUP_SYMBOLS)
        except Exception as exc:
            logger.warning("sql warm filings failed: %s", exc)

    async def _warm_bars(self, symbols: list[str]) -> None:
        alpaca = get_alpaca_source()
        rows: list[tuple] = []
        for sym in symbols:
            try:
                bars = await alpaca.get_stock_bars(sym, period="1y", interval="1d")
            except Exception:
                bars = []
            for b in bars:
                rows.append(
                    (sym, b.timestamp.replace(tzinfo=None), b.open, b.high, b.low, b.close, b.volume)
                )
        if not rows:
            return
        self.con.execute("DELETE FROM bars WHERE symbol IN (SELECT * FROM (VALUES " +
                         ",".join(f"('{s}')" for s in symbols) + ") AS t(s))")
        self.con.executemany(
            "INSERT INTO bars VALUES (?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        logger.info("sql.bars warm: %d rows across %d symbols", len(rows), len(symbols))

    async def _warm_macro(self, series_ids: list[str]) -> None:
        fred = FredSource()
        rows: list[tuple] = []
        for sid in series_ids:
            try:
                series = await fred.get_series(sid, limit=240)
            except Exception:
                continue
            for obs in series.observations:
                rows.append((sid, obs.date, obs.value))
        if not rows:
            return
        placeholders = ",".join(f"'{s}'" for s in series_ids)
        self.con.execute(f"DELETE FROM macro WHERE series_id IN ({placeholders})")
        self.con.executemany("INSERT INTO macro VALUES (?, ?, ?)", rows)
        logger.info("sql.macro warm: %d obs across %d series", len(rows), len(series_ids))

    async def _warm_filings(self, symbols: list[str]) -> None:
        edgar = SecEdgarSource()
        rows: list[tuple] = []
        for sym in symbols:
            try:
                filings = await edgar.recent_filings(sym, limit=20)
            except Exception:
                continue
            for f in filings:
                rows.append(
                    (
                        sym,
                        f.accession_number,
                        f.form_type,
                        f.filed_at.replace(tzinfo=None) if f.filed_at else None,
                        f.primary_document,
                        f.url,
                    )
                )
        if not rows:
            return
        placeholders = ",".join(f"'{s}'" for s in symbols)
        self.con.execute(f"DELETE FROM filings WHERE symbol IN ({placeholders})")
        self.con.executemany("INSERT INTO filings VALUES (?, ?, ?, ?, ?, ?)", rows)
        logger.info("sql.filings warm: %d rows across %d symbols", len(rows), len(symbols))

    # ── querying ─────────────────────────────────────────────────────────

    def list_tables(self) -> list[dict[str, Any]]:
        rows = self.con.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema='main' ORDER BY 1"
        ).fetchall()
        out: list[dict[str, Any]] = []
        for (name,) in rows:
            cols = self.con.execute(
                f"PRAGMA table_info('{name}')"
            ).fetchall()
            row_count = self.con.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
            out.append(
                {
                    "name": name,
                    "row_count": int(row_count),
                    "columns": [
                        {"name": c[1], "type": c[2]} for c in cols
                    ],
                }
            )
        return out

    @staticmethod
    def _validate(query: str) -> str:
        if not query or not query.strip():
            raise ValueError("empty query")
        # Reject multiple statements: a trailing ';' is fine but only one is.
        stripped = query.strip().rstrip(";")
        if ";" in stripped:
            raise ValueError("only one statement per query")
        if not _READONLY_LEADING.match(stripped):
            raise ValueError("only SELECT / WITH / EXPLAIN / PRAGMA / SHOW / DESCRIBE allowed")
        if _FORBIDDEN.search(stripped):
            raise ValueError("write/DDL keywords are not allowed")
        return stripped

    async def query(self, query: str, max_rows: int | None = None) -> dict[str, Any]:
        cleaned = self._validate(query)
        cap = min(max_rows or settings.sql_query_max_rows, settings.sql_query_max_rows)
        loop = asyncio.get_running_loop()

        def _run() -> dict[str, Any]:
            t0 = time.perf_counter()
            cur = self.con.execute(cleaned)
            cols = [d[0] for d in (cur.description or [])]
            data = cur.fetchmany(cap + 1)
            truncated = len(data) > cap
            data = data[:cap]
            elapsed_ms = int((time.perf_counter() - t0) * 1000)
            rows = [
                {col: _stringify(value) for col, value in zip(cols, row)} for row in data
            ]
            return {
                "columns": cols,
                "rows": rows,
                "row_count": len(rows),
                "truncated": truncated,
                "elapsed_ms": elapsed_ms,
            }

        try:
            return await asyncio.wait_for(
                loop.run_in_executor(None, _run),
                timeout=settings.sql_query_timeout_seconds,
            )
        except asyncio.TimeoutError as exc:
            raise TimeoutError(
                f"query exceeded {settings.sql_query_timeout_seconds}s timeout"
            ) from exc


def _stringify(value: Any) -> Any:
    """JSON-safe serialization for cell values returned to the frontend."""
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


engine = SqlEngine()
