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
from datetime import datetime, timedelta, timezone
from typing import Any

import duckdb
import httpx
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


# Securities a stock screener shouldn't list. Calibrated on Alpaca's asset
# names, with two traps checked: "depositary shares" alone would also drop
# ADRs (TSM, BABA), and "units" alone would drop MLPs, whose equity is
# "Common Units" (EPD, ET, MPLX).
_NON_COMMON = re.compile(
    r"\bpreferred\b|\bpfd\b|\bwarrants?\b|(?<!common )(?<!partner )\bunits\b|\brights\b"
    r"|\bnotes due\b|\bdebentures?\b|\bsenior notes\b",
    re.IGNORECASE,
)


def _screenable(asset: dict) -> bool:
    """Exchange-listed common stock or ETF.

    Leaves out OTC (thin, often stale prints) and listed non-common securities:
    preferreds, warrants, rights, SPAC units, baby bonds. Together they were
    about 2,500 of 14,400 Alpaca assets and most of the junk at the top of the
    oversold screen once real volume let them past the liquidity filter.
    """
    sym = asset.get("symbol") or ""
    if not sym or "/" in sym or not asset.get("tradable", True):
        return False
    if asset.get("exchange") == "OTC" or ".PR" in sym:
        return False
    return not _NON_COMMON.search(asset.get("name") or "")


_COMPANY_NAME = re.compile(
    r"\b(inc|corp|corporation|company|holdings?|ltd|limited|plc|group|bancorp|bancshares)\b",
    re.IGNORECASE,
)
_CRYPTO_NAME = re.compile(r"\b(bitcoin|ether|ethereum|solana|xrp|crypto|digital assets?)\b", re.IGNORECASE)


def _investment_product(asset: dict) -> bool:
    """ETFs, ETNs, commodity pools and grantor trusts: screenable on price,
    but company fundamentals don't apply to them.

    The ones that file 10-Ks (gold and silver trusts, commodity pools, crypto
    trusts) carry "net income" from marking their holdings, which gave SLV and
    SIVR a P/E and put them at the top of the Value screen. Some ETNs share
    their issuing bank's CIK in SEC's ticker list, so AMJB inherited
    JPMorgan's margins. Listing venue separates them cleanly: every such
    product in the data trades on NYSE Arca or Cboe, and every bank, REIT and
    BDC with the same "no revenue tag" shape on NYSE or Nasdaq. Crypto trusts
    list on Nasdaq too (IBIT, ETHA), so they're caught by name. A name that
    reads as a company ("Inc", "Corp", "Holdings") is never a product, which
    keeps Cboe Global Markets, listed on its own exchange, and crypto
    operating companies such as Bitcoin Depot.
    """
    name = asset.get("name") or ""
    if _COMPANY_NAME.search(name):
        return False
    return asset.get("exchange") in ("ARCA", "BATS") or bool(_CRYPTO_NAME.search(name))


class RefreshInProgress(RuntimeError):
    """A universe refresh is already running; the caller should not queue another."""


FUNDAMENTALS_COLUMNS = (
    "symbol", "cik", "shares_out", "ttm_revenue", "ttm_net_income", "equity",
    "revenue_growth_pct", "public_float", "period_end", "fetched_at",
)
FUNDAMENTALS_DDL = """
            CREATE TABLE {exists}{table} (
                symbol TEXT,
                cik TEXT,
                shares_out DOUBLE,
                ttm_revenue DOUBLE,
                ttm_net_income DOUBLE,
                equity DOUBLE,
                revenue_growth_pct DOUBLE,
                public_float DOUBLE,
                period_end DATE,
                fetched_at TIMESTAMP
            )"""

# Market cap from shares x price must land within this multiple of the filer's
# reported public float. Wide enough for a year of price moves (the float is
# measured at the end of the prior Q2), tight enough to catch a share count in
# the wrong units: Berkshire reports diluted shares in Class A equivalents,
# which priced at BRK.B gave a $0.8B "market cap", and a preferred ticker
# sharing its issuer's CIK gets the common share count at a $25 price.
FLOAT_BAND = (0.2, 5.0)


def _plausible_market_cap(shares: float | None, price: float | None, public_float: float | None) -> bool:
    if not shares or not price:
        return False
    if not public_float:
        return True  # nothing to check against; trust the filing
    ratio = float(shares) * float(price) / float(public_float)
    return FLOAT_BAND[0] <= ratio <= FLOAT_BAND[1]


class _Pacer:
    """Spaces request starts to stay under a per-second limit across tasks."""

    def __init__(self, per_second: float) -> None:
        self._interval = 1.0 / per_second
        self._next = 0.0
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        async with self._lock:
            loop = asyncio.get_running_loop()
            now = loop.time()
            if now < self._next:
                await asyncio.sleep(self._next - now)
                now = loop.time()
            self._next = now + self._interval


def _parse_facts(body: bytes, today, extract) -> dict | None:
    """json.loads plus extraction, run on a worker thread: large filers'
    companyfacts run to several MB, too slow to parse on the event loop."""
    import json

    try:
        return extract(json.loads(body), today)
    except Exception:
        return None


def _adjust_spin_offs(
    cur: "duckdb.DuckDBPyConnection", spin_offs: list[dict], table: str = "bars_next"
) -> dict[str, int]:
    """Back-adjust parent prices for spin-offs so the distribution doesn't read
    as a crash.

    Value method, using only ex-date closes so the day's market move stays out
    of the factor:

        f = P_parent / (P_parent + ratio * P_child)

    and every parent bar before the ex-date is scaled by f. Volume is left
    alone; a spin-off doesn't change the parent's share count.

    Factors are all computed before any are applied. A parent with two
    spin-offs in the window would otherwise have its earlier ex-date close
    already scaled by the later factor, skewing the earlier one.
    """
    factors: list[tuple[str, Any, float]] = []
    skipped = 0
    for so in spin_offs:
        row = cur.execute(
            f"""
            SELECT p.timestamp, p.close, c.close
            FROM {table} p
            JOIN {table} c ON c.symbol = ? AND c.timestamp = p.timestamp
            WHERE p.symbol = ? AND p.timestamp >= CAST(? AS TIMESTAMP)
            ORDER BY p.timestamp
            LIMIT 1
            """,
            [so["child"], so["parent"], so["ex_date"]],
        ).fetchone()
        if not row:
            # Child isn't in the universe (escrow/CVR CUSIPs, OTC listings) or
            # the ex-date is outside the window.
            skipped += 1
            continue
        ex_ts, p_parent, p_child = row
        if not p_parent or not p_child or p_parent <= 0 or p_child <= 0:
            skipped += 1
            continue
        f = p_parent / (p_parent + so["ratio"] * p_child)
        if not (0.0 < f < 1.0):
            skipped += 1
            continue
        factors.append((so["parent"], ex_ts, f))

    for parent, ex_ts, f in factors:
        cur.execute(
            f"UPDATE {table} SET open = open * ?, high = high * ?, low = low * ?, close = close * ? "
            "WHERE symbol = ? AND timestamp < ?",
            [f, f, f, f, parent, ex_ts],
        )
    return {"applied": len(factors), "skipped": skipped}


def _insert_bars(cur: "duckdb.DuckDBPyConnection", by_symbol: dict[str, list]) -> int:
    """Build one chunk's frame and bulk-insert it. Runs on a worker thread."""
    frame = pd.DataFrame(
        [(sym, *bar) for sym, bars in by_symbol.items() for bar in bars],
        columns=["symbol", "timestamp", "open", "high", "low", "close", "volume"],
    )
    if frame.empty:
        return 0
    _insert_frame(cur, frame)
    return len(frame)


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
            CREATE TABLE IF NOT EXISTS universe_assets (
                symbol TEXT,
                name TEXT,
                exchange TEXT,
                investment_product BOOLEAN
            );
            """ + FUNDAMENTALS_DDL.format(table="fundamentals", exists="IF NOT EXISTS ") + ";"
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
        screenable = [a for a in assets if _screenable(a)]
        symbols = [a["symbol"] for a in screenable]
        if limit:
            symbols = symbols[:limit]
        if not symbols:
            return 0

        if self._refresh_lock.locked():
            raise RefreshInProgress("a universe refresh is already running")

        async with self._refresh_lock:
            return await self._refresh_universe_locked(alpaca, symbols, screenable)

    async def _refresh_universe_locked(self, alpaca, symbols: list[str], assets: list[dict] | None = None) -> int:
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
                # Frame construction (~130k tuples) runs on the worker too; on
                # the loop it cost a few hundred ms per chunk on Railway's CPUs.
                inserted = await asyncio.to_thread(_insert_bars, cur, by_symbol)
                if inserted:
                    total += inserted
                    seen.update(by_symbol)
                del by_symbol

            if total == 0:
                logger.warning("screener universe refresh returned no bars")
                await asyncio.to_thread(cur.execute, "DROP TABLE IF EXISTS bars_next")
                return 0

            # Split adjustment comes from Alpaca; spin-offs don't, so back-adjust
            # them here. Best-effort: a corporate-actions outage leaves those few
            # parents unadjusted rather than failing the whole refresh.
            try:
                today = datetime.now(timezone.utc).date()
                spins = await alpaca.get_spin_offs(
                    (today - timedelta(days=400)).isoformat(), today.isoformat()
                )
                if spins:
                    stats = await asyncio.to_thread(_adjust_spin_offs, cur, spins)
                    logger.info(
                        "screener spin-off adjustment",
                        extra={"spin_offs": len(spins), **stats},
                    )
            except Exception as exc:
                logger.warning("spin-off adjustment skipped: %s", exc)

            meta = pd.DataFrame(
                [(a["symbol"], a.get("name"), a.get("exchange"), _investment_product(a))
                 for a in (assets or [])],
                columns=["symbol", "name", "exchange", "investment_product"],
            )

            def _swap() -> None:
                cur.execute("BEGIN")
                cur.execute("DROP TABLE bars")
                cur.execute("ALTER TABLE bars_next RENAME TO bars")
                if not meta.empty:
                    cur.execute("DELETE FROM universe_assets")
                    cur.register("meta_chunk", meta)
                    try:
                        cur.execute("INSERT INTO universe_assets SELECT * FROM meta_chunk")
                    finally:
                        cur.unregister("meta_chunk")
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

    # ── fundamentals (SEC XBRL) ──────────────────────────────────────────

    def fundamentals_age_days(self) -> float | None:
        """Days since the last fundamentals refresh, or None if never."""
        row = self.con.cursor().execute("SELECT MAX(fetched_at) FROM fundamentals").fetchone()
        if not row or row[0] is None:
            return None
        return (datetime.now(timezone.utc).replace(tzinfo=None) - row[0]).total_seconds() / 86400

    async def refresh_fundamentals(self, limit: int | None = None) -> int:
        """Pull TTM fundamentals from SEC XBRL for every universe symbol with a
        CIK, then rebuild the screener metrics. Returns symbols covered.

        ~7k filers at SEC's fair-access pace takes around 20 minutes, so it runs
        weekly rather than nightly; filings only change quarterly anyway. Shares
        the refresh lock with the universe ingest, since both rebuild metrics.
        """
        from .xbrl import extract_fundamentals

        if self._refresh_lock.locked():
            raise RefreshInProgress("a refresh is already running")
        async with self._refresh_lock:
            cur = self.con.cursor()
            prices = {
                sym: float(px) for sym, px in await asyncio.to_thread(
                    lambda: cur.execute("SELECT symbol, price FROM screener_metrics").fetchall()
                ) if px is not None
            }
            if not prices:
                logger.info("fundamentals skipped: screener universe is empty")
                return 0
            products = {
                r[0] for r in await asyncio.to_thread(
                    lambda: cur.execute(
                        "SELECT symbol FROM universe_assets WHERE investment_product"
                    ).fetchall()
                )
            }
            for sym in products:
                prices.pop(sym, None)

            edgar = SecEdgarSource()
            tickers = await edgar.ticker_map()
            by_cik: dict[str, list[str]] = {}
            for sym in prices:
                # SEC writes class suffixes with a dash (BRK-B); Alpaca with a dot.
                cik = tickers.get(sym) or tickers.get(sym.replace(".", "-"))
                if cik:
                    by_cik.setdefault(cik, []).append(sym)
            ciks = sorted(by_cik)
            if limit:
                ciks = ciks[:limit]

            today = datetime.now(timezone.utc).date()
            fetched_at = datetime.now(timezone.utc).replace(tzinfo=None)
            rows: list[tuple] = []
            pace = _Pacer(per_second=8)  # SEC allows 10/s
            sem = asyncio.Semaphore(4)

            async def one(client: httpx.AsyncClient, cik: str) -> None:
                async with sem:
                    await pace.wait()
                    try:
                        body = await edgar.company_facts(client, cik)
                    except Exception as exc:
                        logger.debug("companyfacts %s failed: %s", cik, exc)
                        return
                if body is None:
                    return
                f = await asyncio.to_thread(_parse_facts, body, today, extract_fundamentals)
                if f is None:
                    return
                for sym in by_cik[cik]:
                    # Checked per ticker: one CIK can list share classes and
                    # preferreds at very different prices, and the company-wide
                    # share count is only right for some of them.
                    shares = f["shares_out"]
                    if not _plausible_market_cap(shares, prices.get(sym), f["public_float"]):
                        shares = None
                    rows.append((
                        sym, cik, shares, f["ttm_revenue"], f["ttm_net_income"], f["equity"],
                        f["revenue_growth_pct"], f["public_float"], f["period_end"], fetched_at,
                    ))

            async with httpx.AsyncClient(timeout=60.0) as client:
                await asyncio.gather(*(one(client, c) for c in ciks))

            if not rows:
                logger.warning("fundamentals refresh produced no rows")
                return 0

            frame = pd.DataFrame(rows, columns=list(FUNDAMENTALS_COLUMNS))

            def _store() -> None:
                cur.execute("DROP TABLE IF EXISTS fundamentals_next")
                # Explicit DDL rather than copying the live table's shape, so a
                # new column lands on the first refresh after a deploy.
                cur.execute(FUNDAMENTALS_DDL.format(table="fundamentals_next", exists=""))
                cur.register("fund_chunk", frame)
                try:
                    cur.execute("INSERT INTO fundamentals_next SELECT * FROM fund_chunk")
                finally:
                    cur.unregister("fund_chunk")
                cur.execute("BEGIN")
                cur.execute("DROP TABLE fundamentals")
                cur.execute("ALTER TABLE fundamentals_next RENAME TO fundamentals")
                cur.execute("COMMIT")

            await asyncio.to_thread(_store)
            await asyncio.to_thread(self._rebuild_metrics, cur)
            logger.info(
                "fundamentals refreshed",
                extra={"symbols": len(rows), "filers": len(ciks)},
            )
            return len(rows)

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
