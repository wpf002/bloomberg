import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

import asyncpg
import redis.asyncio as redis

from .config import settings

logger = logging.getLogger(__name__)


class Database:
    pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        if self.pool is not None:
            return
        # `parsed_postgres` honours DATABASE_URL (Railway/Heroku) when set,
        # otherwise falls back to the per-component POSTGRES_* env vars
        # used by docker-compose.
        params = settings.parsed_postgres
        # Railway managed Postgres requires SSL — auto-enable when the
        # DATABASE_URL host isn't a local address.
        ssl = None
        if settings.database_url:
            host = params.get("host") or ""
            if host and host not in {"localhost", "127.0.0.1", "postgres"}:
                ssl = "require"
        self.pool = await asyncpg.create_pool(
            **params,
            ssl=ssl,
            min_size=1,
            max_size=10,
            command_timeout=30,
        )
        logger.info("PostgreSQL pool ready: %s:%s", params["host"], params["port"])

    async def disconnect(self) -> None:
        if self.pool is not None:
            await self.pool.close()
            self.pool = None
            logger.info("PostgreSQL pool closed")

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[asyncpg.Connection]:
        if self.pool is None:
            raise RuntimeError("Database pool is not initialized")
        async with self.pool.acquire() as connection:
            yield connection


class Cache:
    client: redis.Redis | None = None

    async def connect(self) -> None:
        if self.client is not None:
            return
        self.client = redis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
        await self.client.ping()
        logger.info("Redis connected: %s", settings.redis_url.split("@")[-1])

    async def disconnect(self) -> None:
        if self.client is not None:
            await self.client.close()
            self.client = None
            logger.info("Redis disconnected")


database = Database()
cache = Cache()
