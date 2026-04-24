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
        self.pool = await asyncpg.create_pool(
            user=settings.postgres_user,
            password=settings.postgres_password,
            database=settings.postgres_db,
            host=settings.postgres_host,
            port=settings.postgres_port,
            min_size=1,
            max_size=10,
            command_timeout=30,
        )
        logger.info("PostgreSQL pool ready: %s:%s", settings.postgres_host, settings.postgres_port)

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
        logger.info("Redis connected: %s:%s", settings.redis_host, settings.redis_port)

    async def disconnect(self) -> None:
        if self.client is not None:
            await self.client.close()
            self.client = None
            logger.info("Redis disconnected")


database = Database()
cache = Cache()
