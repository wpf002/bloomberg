"""Idempotent Postgres + TimescaleDB schema bootstrap.

Phase 6 introduced per-user persistence (GitHub OAuth + watchlists +
layouts + alerts). AURORA Module 5 extends this with TimescaleDB
hypertables for:

  - market_data           (per-symbol tick / quote stream)
  - macro_series          (FRED observations)
  - normalized_records    (everything that flowed through the normalizer)
  - audit_log             (one row per ingested record + endpoint hit)
  - risk_snapshots        (historical risk-engine outputs)
  - intelligence_snapshots (historical intelligence-engine outputs +
                            the input data that produced them)

`CREATE EXTENSION IF NOT EXISTS timescaledb` and `create_hypertable(...,
if_not_exists => TRUE)` make this safe to re-run on every startup. On a
plain Postgres image the extension fails to load — we catch and log so
existing Phase-6 functionality keeps working in dev environments that
haven't bumped the postgres image yet.
"""

from __future__ import annotations

import logging

from .database import database

logger = logging.getLogger(__name__)


# Phase-6 base schema. Identical to the original; the AURORA changes are
# additive and live in HYPERTABLE_SQL below.
BASE_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id            BIGSERIAL PRIMARY KEY,
    github_id     TEXT UNIQUE NOT NULL,
    login         TEXT NOT NULL,
    name          TEXT,
    email         TEXT,
    avatar_url    TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_login_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS user_watchlists (
    user_id    BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    symbols    JSONB NOT NULL DEFAULT '[]'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS user_layouts (
    user_id    BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    layouts    JSONB NOT NULL DEFAULT '{}'::jsonb,
    hidden     JSONB NOT NULL DEFAULT '[]'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS user_alert_rules (
    id         TEXT PRIMARY KEY,
    user_id    BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    payload    JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS user_alert_rules_user_idx
    ON user_alert_rules(user_id);

CREATE TABLE IF NOT EXISTS shared_layouts (
    slug         TEXT PRIMARY KEY,
    owner_user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name         TEXT NOT NULL,
    layouts      JSONB NOT NULL,
    hidden       JSONB NOT NULL DEFAULT '[]'::jsonb,
    view_count   BIGINT NOT NULL DEFAULT 0,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS shared_layouts_owner_idx
    ON shared_layouts(owner_user_id);

-- V2.2: manually-tracked positions. Not a hypertable — one row per
-- holding, edited interactively. user_id may be NULL when the user
-- isn't signed in (the row is then keyed by a client-provided
-- session token in the future; for now, anonymous rows are scoped to
-- a special user_id = 0 sentinel).
CREATE TABLE IF NOT EXISTS manual_positions (
    id          BIGSERIAL PRIMARY KEY,
    user_id     BIGINT NOT NULL DEFAULT 0,
    symbol      TEXT   NOT NULL,
    quantity    DOUBLE PRECISION NOT NULL,
    cost_basis  DOUBLE PRECISION NOT NULL,
    entry_date  DATE,
    notes       TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS manual_positions_user_idx
    ON manual_positions (user_id, symbol);
"""


# AURORA Module 5: time-series tables. Each gets converted to a hypertable
# below with an explicit chunk interval. Time-bucket choices reflect the
# natural cadence of the data: 1-week chunks for tick data (small chunks,
# fast scans for recent windows), 1-month chunks for daily/macro series.
HYPERTABLE_DDL = """
CREATE TABLE IF NOT EXISTS market_data (
    time      TIMESTAMPTZ NOT NULL,
    symbol    TEXT NOT NULL,
    price     DOUBLE PRECISION,
    volume    DOUBLE PRECISION,
    source    TEXT NOT NULL,
    raw       JSONB
);
CREATE INDEX IF NOT EXISTS market_data_symbol_time_idx
    ON market_data (symbol, time DESC);

CREATE TABLE IF NOT EXISTS macro_series (
    time       TIMESTAMPTZ NOT NULL,
    series_id  TEXT NOT NULL,
    value      DOUBLE PRECISION,
    source     TEXT NOT NULL DEFAULT 'fred',
    unit       TEXT,
    frequency  TEXT
);
CREATE INDEX IF NOT EXISTS macro_series_id_time_idx
    ON macro_series (series_id, time DESC);

CREATE TABLE IF NOT EXISTS normalized_records (
    ingested_at  TIMESTAMPTZ NOT NULL,
    timestamp    TIMESTAMPTZ NOT NULL,
    source       TEXT NOT NULL,
    symbol       TEXT NOT NULL,
    series_id    TEXT NOT NULL,
    value        DOUBLE PRECISION,
    unit         TEXT,
    tags         JSONB
);
CREATE INDEX IF NOT EXISTS normalized_records_symbol_idx
    ON normalized_records (symbol, ingested_at DESC);

CREATE TABLE IF NOT EXISTS audit_log (
    ingested_at      TIMESTAMPTZ NOT NULL,
    record_id        TEXT,
    source           TEXT NOT NULL,
    symbol           TEXT NOT NULL,
    endpoint_called  TEXT,
    user_id          BIGINT
);
CREATE INDEX IF NOT EXISTS audit_log_symbol_idx
    ON audit_log (symbol, ingested_at DESC);

CREATE TABLE IF NOT EXISTS risk_snapshots (
    captured_at  TIMESTAMPTZ NOT NULL,
    kind         TEXT NOT NULL,
    user_id      BIGINT,
    output       JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS risk_snapshots_kind_idx
    ON risk_snapshots (kind, captured_at DESC);

CREATE TABLE IF NOT EXISTS intelligence_snapshots (
    captured_at  TIMESTAMPTZ NOT NULL,
    kind         TEXT NOT NULL,
    inputs_hash  TEXT,
    inputs       JSONB NOT NULL,
    output       JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS intelligence_snapshots_kind_idx
    ON intelligence_snapshots (kind, captured_at DESC);
"""


# create_hypertable + retention/compression policies. Each statement is
# wrapped in a DO block so a failure in one (e.g., timescaledb extension
# unavailable) doesn't abort the rest.
HYPERTABLE_POLICIES = """
SELECT create_hypertable('market_data', 'time',
    chunk_time_interval => INTERVAL '1 week',
    if_not_exists => TRUE);

SELECT create_hypertable('macro_series', 'time',
    chunk_time_interval => INTERVAL '1 month',
    if_not_exists => TRUE);

SELECT create_hypertable('normalized_records', 'ingested_at',
    chunk_time_interval => INTERVAL '1 week',
    if_not_exists => TRUE);

SELECT create_hypertable('audit_log', 'ingested_at',
    chunk_time_interval => INTERVAL '1 week',
    if_not_exists => TRUE);

SELECT create_hypertable('risk_snapshots', 'captured_at',
    chunk_time_interval => INTERVAL '1 month',
    if_not_exists => TRUE);

SELECT create_hypertable('intelligence_snapshots', 'captured_at',
    chunk_time_interval => INTERVAL '1 month',
    if_not_exists => TRUE);

-- Compression policies. Tick data: compress chunks >7d old. Daily/macro:
-- compress >30d old. Re-running is harmless (add_compression_policy is
-- idempotent in modern Timescale).
ALTER TABLE market_data        SET (timescaledb.compress, timescaledb.compress_segmentby = 'symbol');
ALTER TABLE normalized_records SET (timescaledb.compress, timescaledb.compress_segmentby = 'symbol');
ALTER TABLE audit_log          SET (timescaledb.compress, timescaledb.compress_segmentby = 'symbol');
ALTER TABLE macro_series       SET (timescaledb.compress, timescaledb.compress_segmentby = 'series_id');
ALTER TABLE risk_snapshots         SET (timescaledb.compress);
ALTER TABLE intelligence_snapshots SET (timescaledb.compress);

SELECT add_compression_policy('market_data',          INTERVAL '7 days',  if_not_exists => TRUE);
SELECT add_compression_policy('normalized_records',   INTERVAL '7 days',  if_not_exists => TRUE);
SELECT add_compression_policy('audit_log',            INTERVAL '7 days',  if_not_exists => TRUE);
SELECT add_compression_policy('macro_series',         INTERVAL '30 days', if_not_exists => TRUE);
SELECT add_compression_policy('risk_snapshots',       INTERVAL '30 days', if_not_exists => TRUE);
SELECT add_compression_policy('intelligence_snapshots', INTERVAL '30 days', if_not_exists => TRUE);
"""


async def _execute_isolated(sql: str, *, label: str) -> bool:
    """Run a single SQL block on a fresh connection from the pool.

    A failure inside `CREATE EXTENSION timescaledb` aborts the asyncpg
    connection (the wire protocol gets out of sync), so any subsequent
    `conn.execute(...)` on the same connection silently fails. Acquiring
    a fresh connection per phase keeps later phases from being collateral
    damage of an earlier failure.
    """
    if database.pool is None:
        return False
    try:
        async with database.acquire() as conn:
            await conn.execute(sql)
        return True
    except Exception as exc:
        logger.warning("%s failed (non-fatal): %s", label, exc)
        return False


async def ensure_schema() -> None:
    if database.pool is None:
        logger.warning("ensure_schema: pool unavailable, skipping bootstrap")
        return

    # 1. Try the TimescaleDB extension on a dedicated connection.
    timescale_available = await _execute_isolated(
        "CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;",
        label="timescaledb extension",
    )
    if not timescale_available:
        logger.warning(
            "TimescaleDB extension unavailable — hypertable policies will be skipped"
        )

    # 2. Phase-6 base schema (always runs).
    await _execute_isolated(BASE_SCHEMA_SQL, label="base schema")

    # 3. AURORA tables. These are plain CREATE TABLE statements that work
    #    even without TimescaleDB — promotion to hypertable happens in
    #    phase 4 only when the extension is available.
    await _execute_isolated(HYPERTABLE_DDL, label="hypertable DDL")

    # 4. Hypertable + compression policies. Skip when timescaledb wasn't
    #    loaded; the regular tables from step 3 will still serve audit
    #    log reads (just without time-series partitioning).
    if timescale_available:
        await _execute_isolated(HYPERTABLE_POLICIES, label="hypertable policies")

    logger.info(
        "Postgres schema ready (base + AURORA tables%s)",
        " + timescale hypertables" if timescale_available else "",
    )
