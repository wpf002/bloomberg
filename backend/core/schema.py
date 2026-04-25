"""Idempotent Postgres schema bootstrap.

Phase 6 introduces per-user persistence: GitHub-OAuth-backed `users`,
their `user_watchlists`, `user_layouts`, and per-user `user_alert_rules`.
We deliberately keep this in code rather than reaching for a migration
framework — the surface area is small and `CREATE TABLE IF NOT EXISTS`
is fine here. Run on FastAPI startup after the asyncpg pool connects.
"""

from __future__ import annotations

import logging

from .database import database

logger = logging.getLogger(__name__)


SCHEMA_SQL = """
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
"""


async def ensure_schema() -> None:
    if database.pool is None:
        logger.warning("ensure_schema: pool unavailable, skipping bootstrap")
        return
    async with database.acquire() as conn:
        await conn.execute(SCHEMA_SQL)
    logger.info("Postgres schema ready (users/watchlists/layouts/alert_rules)")
