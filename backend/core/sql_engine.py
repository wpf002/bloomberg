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
import pandas as pd

from ..data.sources import FredSource, SecEdgarSource, get_alpaca_source
from .config import settings

logger = logging.getLogger(__name__)


# Resolved at call time from settings — see config.sql_warm_symbols /
# sql_warm_macro_series. Operators can override via SQL_WARM_SYMBOLS and
# SQL_WARM_MACRO_SERIES env vars without changing code.

_READONLY_LEADING = re.compile(r"^\s*(WITH|SELECT|EXPLAIN|PRAGMA|SHOW|DESCRIBE)\b", re.IGNORECASE)
_FORBIDDEN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|ATTACH|COPY|EXPORT|IMPORT|"
    r"TRUNCATE|REINDEX|CALL|VACUUM|LOAD|INSTALL)\b",
    re.IGNORECASE,
)


class RefreshInProgress(RuntimeError):
    """A universe refresh is already running; the caller should not queue another."""


def _insert_frame(cur: "duckdb.DuckDBPyConnection", frame: "pd.DataFrame") -> None:
    """Bulk-insert one chunk of bars. Registering the frame lets DuckDB read
    it column-wise in a single statement, instead of binding row by row."""
    cur.register("bars_chunk", frame)
    try:
        cur.execute("INSERT INTO bars_next SELECT * FROM bars_chunk")
    finally:
        cur.unregister("bars_chunk")


class SqlEngine:
    """Wraps a single in-memory DuckDB connection. All ingestion happens via
    Pandas DataFrames (DuckDB's native frame interop) — we lean on the
    versions of pandas / numpy already pinned for the rest of the backend.
    """

    def __init__(self) -> None:
        # File-backed by default so the screener universe spills to disk rather
        # than living entirely in RAM. Falls back to in-memory if the path
        # isn't writable, which keeps local dev and tests working.
        path = settings.duckdb_path or ":memory:"
        try:
            self.con = duckdb.connect(path)
        except Exception as exc:
            logger.warning("duckdb at %s unavailable (%s); using in-memory", path, exc)
            self.con = duckdb.connect(":memory:")
        try:
            self.con.execute(f"SET memory_limit='{settings.duckdb_memory_limit}'")
        except Exception:
            pass
        self._refresh_lock = asyncio.Lock()
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
        symbols = settings.sql_warm_symbols
        macro_series = settings.sql_warm_macro_series
        try:
            await self._warm_bars(symbols)
        except Exception as exc:
            logger.warning("sql warm bars failed: %s", exc)
        try:
            await self._warm_macro(macro_series)
        except Exception as exc:
            logger.warning("sql warm macro failed: %s", exc)
        try:
            await self._warm_filings(symbols)
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

    # ── screener universe ────────────────────────────────────────────────

    async def refresh_universe(self, limit: int | None = None) -> int:
        """Load daily bars for the whole tradable equity universe into `bars`.

        `warm()` loads a handful of symbols for the SQL workbench; the screener
        needs breadth, so this pulls Alpaca's active-asset list and fetches it
        through the multi-symbol bars endpoint. Returns the row count written.

        Runs on a schedule rather than per-request: a full pass is thousands of
        symbols and takes minutes.
        """
        alpaca = get_alpaca_source()
        if not alpaca.credentials_configured():
            logger.info("screener universe refresh skipped: no Alpaca credentials")
            return 0

        assets = await alpaca.list_active_assets()
        symbols = [
            a["symbol"] for a in assets
            if a.get("symbol") and a.get("tradable", True) and "/" not in a["symbol"]
        ]
        if limit:
            symbols = symbols[:limit]
        if not symbols:
            return 0

        if self._refresh_lock.locked():
            raise RefreshInProgress("a universe refresh is already running")

        async with self._refresh_lock:
            return await self._refresh_universe_locked(alpaca, symbols)

    async def _refresh_universe_locked(self, alpaca, symbols: list[str]) -> int:
        # Every DuckDB call here runs on a worker thread through its own
        # cursor. Running them on the event loop blocked the whole process
        # between chunks — in production a refresh stalled HTTP and the bot
        # manager's tick loop for 30+ minutes. A cursor is a separate DuckDB
        # connection to the same database, so this never shares a connection
        # object with the loop thread or with a concurrent screen.
        #
        # Rows go in as one DataFrame per chunk rather than `executemany`,
        # which binds row by row and was the bulk of that 30 minutes.
        #
        # Build into a staging table and swap at the end, so a concurrent
        # screen keeps reading the previous universe rather than a half-filled
        # one. Insert per chunk instead of accumulating: a full pass is ~3.2M
        # rows, and holding them all peaked at ~3.2GB.
        cur = self.con.cursor()

        def _prepare() -> None:
            cur.execute("DROP TABLE IF EXISTS bars_next")
            cur.execute("CREATE TABLE bars_next AS SELECT * FROM bars WHERE FALSE")

        await asyncio.to_thread(_prepare)

        total = 0
        seen: set[str] = set()
        CHUNK = 500
        try:
            for i in range(0, len(symbols), CHUNK):
                batch = symbols[i:i + CHUNK]
                by_symbol = await alpaca.get_bars_multi(batch, days=400, chunk=CHUNK, raw=True)
                frame = pd.DataFrame(
                    [(sym, *bar) for sym, bars in by_symbol.items() for bar in bars],
                    columns=["symbol", "timestamp", "open", "high", "low", "close", "volume"],
                )
                if not frame.empty:
                    await asyncio.to_thread(_insert_frame, cur, frame)
                    total += len(frame)
                    seen.update(by_symbol)
                del by_symbol, frame

            if total == 0:
                logger.warning("screener universe refresh returned no bars")
                await asyncio.to_thread(cur.execute, "DROP TABLE IF EXISTS bars_next")
                return 0

            def _swap() -> None:
                cur.execute("BEGIN")
                cur.execute("DROP TABLE bars")
                cur.execute("ALTER TABLE bars_next RENAME TO bars")
                cur.execute("COMMIT")

            await asyncio.to_thread(_swap)
        except Exception:
            def _cleanup() -> None:
                try:
                    cur.execute("ROLLBACK")
                except Exception:
                    pass
                cur.execute("DROP TABLE IF EXISTS bars_next")

            await asyncio.to_thread(_cleanup)
            raise

        await asyncio.to_thread(self._rebuild_metrics, cur)
        logger.info("screener universe: %d rows across %d symbols", total, len(seen))
        return total

    def _rebuild_metrics(self, cur: "duckdb.DuckDBPyConnection | None" = None) -> None:
        """Materialise the screener metrics into `screener_metrics`.

        Computing the window functions on every request meant a full scan of
        3.2M bars per screen (~1s). Doing it once per refresh makes a screen a
        scan of one row per symbol.

        Built in symbol batches: DuckDB's window operators don't spill to disk,
        so running all ~12k symbols in one statement ignored `memory_limit` and
        peaked near 1.8GB. Batching caps the working set to one batch.

        Builds `screener_metrics_next` and swaps, so a screen arriving mid-build
        reads the previous metrics instead of hitting a dropped table.
        """
        from .screener import METRICS_SQL  # local import: screener imports nothing here

        cur = cur or self.con.cursor()
        symbols = [r[0] for r in cur.execute("SELECT DISTINCT symbol FROM bars").fetchall()]
        cur.execute("DROP TABLE IF EXISTS screener_metrics_next")

        created = False
        BATCH = 1500
        for i in range(0, len(symbols), BATCH):
            batch = symbols[i:i + BATCH]
            placeholders = ",".join("?" for _ in batch)
            body = METRICS_SQL.format(min_bars=60, where=f"WHERE symbol IN ({placeholders})")
            if not created:
                cur.execute(f"CREATE TABLE screener_metrics_next AS {body}", batch)
                created = True
            else:
                cur.execute(f"INSERT INTO screener_metrics_next {body}", batch)

        if not created:
            cur.execute(
                "CREATE TABLE screener_metrics_next AS "
                f"{METRICS_SQL.format(min_bars=60, where='')}"
            )

        cur.execute("BEGIN")
        cur.execute("DROP TABLE IF EXISTS screener_metrics")
        cur.execute("ALTER TABLE screener_metrics_next RENAME TO screener_metrics")
        cur.execute("COMMIT")

        count = cur.execute("SELECT COUNT(*) FROM screener_metrics").fetchone()[0]
        logger.info("screener metrics: %d symbols", int(count))

    async def run_screen(self, sql: str, params: list[Any]) -> list[dict[str, Any]]:
        """Execute a screener query built by `core.screener.build_query`.

        Bypasses `_validate` deliberately — the SQL is assembled from a fixed
        template with bound parameters, never from user text. Runs on its own
        cursor so it never shares a connection object with a refresh in flight.
        """
        def _run() -> list[dict[str, Any]]:
            cur = self.con.cursor()
            try:
                res = cur.execute(sql, params)
                cols = [d[0] for d in res.description]
                return [dict(zip(cols, r)) for r in res.fetchall()]
            finally:
                cur.close()

        return await asyncio.to_thread(_run)

    def metrics_ready(self) -> bool:
        row = self.con.execute(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_schema='main' AND table_name='screener_metrics'"
        ).fetchone()
        return bool(row and row[0])

    def universe_size(self) -> int:
        if not self.metrics_ready():
            return 0
        row = self.con.execute("SELECT COUNT(*) FROM screener_metrics").fetchone()
        return int(row[0]) if row else 0

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
            # Own cursor: this runs on an executor thread, and the shared
            # connection object is also used from the event loop.
            cur = self.con.cursor().execute(cleaned)
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
