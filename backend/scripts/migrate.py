"""Idempotent Postgres / TimescaleDB migration runner.

This is the same DDL that lives in `backend.core.schema.ensure_schema`, but
exposed as a CLI entry point so Railway can run it as a one-off pre-deploy
job and (optionally) before every backend boot via the FastAPI lifespan.

Idempotency guarantees:
  - `CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE`
  - `CREATE TABLE IF NOT EXISTS …` for every table
  - `create_hypertable(…, if_not_exists => TRUE)` for every hypertable
  - `add_compression_policy(…, if_not_exists => TRUE)` for every policy

So running this on every deploy is safe — second and subsequent runs are
no-ops on a healthy schema.

Exit codes:
  0  schema is healthy (whether anything had to change or not)
  1  fatal failure (could not connect to Postgres at all)

Run from repo root:
    python -m backend.scripts.migrate
or with uv:
    uv run --python 3.11 python -m backend.scripts.migrate
"""

from __future__ import annotations

import asyncio
import logging
import sys

from backend.core.database import database
from backend.core.schema import ensure_schema

logger = logging.getLogger("migrate")


async def run() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
    )
    try:
        await database.connect()
    except Exception as exc:
        logger.error("could not connect to Postgres: %s", exc)
        return 1

    try:
        await ensure_schema()
        logger.info("migration complete")
        return 0
    except Exception as exc:
        # ensure_schema swallows + logs individual phase failures, so a
        # bubbled exception here is unusual. Treat as fatal.
        logger.exception("migration failed: %s", exc)
        return 1
    finally:
        try:
            await database.disconnect()
        except Exception:
            pass


def main() -> None:
    sys.exit(asyncio.run(run()))


if __name__ == "__main__":
    main()
