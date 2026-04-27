import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import api_router
from .core.alerts import engine as alert_engine
from .core.config import settings
from .core.database import cache, database
from .core.observability import RequestLoggingMiddleware, configure_logging
from .core.schema import ensure_schema
from .core.sql_engine import engine as sql_engine
from .core.streaming import streamer
from .data.sources import SecEdgarSource, get_meilisearch

configure_logging("DEBUG" if settings.debug else "INFO")
logger = logging.getLogger("bloomberg-terminal")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        "starting",
        extra={"app": settings.app_name, "env": settings.app_env, "version": settings.app_version},
    )
    # Phase 1: connect Postgres + run idempotent migration. Failure is
    # non-fatal — the app still serves cached / synthetic data, and
    # /healthz reports `db: degraded` so a cluster can drop the pod.
    try:
        await database.connect()
        await ensure_schema()
        logger.info("migration ok")
    except Exception as exc:
        logger.warning("postgres unavailable at startup: %s", exc)
    try:
        await cache.connect()
    except Exception as exc:
        logger.warning("redis unavailable at startup: %s", exc)
    try:
        await streamer.start()
        await alert_engine.start()
    except Exception as exc:
        logger.warning("stream/alert background tasks failed to start: %s", exc)
    # Meilisearch index bootstrap + DuckDB warm-up are best-effort and run
    # in the background so the server can accept requests immediately.
    asyncio.create_task(_bootstrap_search_and_sql())
    # Phase 7: re-index default-watchlist filings metadata once a day so the
    # SRCH panel stays current without anyone having to click "Index".
    asyncio.create_task(_filings_indexer_cron())
    yield
    try:
        await alert_engine.stop()
        await streamer.stop()
    except Exception as exc:
        logger.warning("stream/alert background tasks shutdown error: %s", exc)
    await database.disconnect()
    await cache.disconnect()


FILINGS_SEED_SYMBOLS = ["AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "GOOGL", "META", "QQQ"]
FILINGS_INDEX_INTERVAL_SECONDS = 24 * 60 * 60  # daily


async def _bootstrap_search_and_sql() -> None:
    meili = get_meilisearch()
    try:
        await meili.ensure_index()
    except Exception as exc:
        logger.warning("meilisearch bootstrap failed (non-fatal): %s", exc)
    try:
        await sql_engine.warm()
    except Exception as exc:
        logger.warning("duckdb warm failed (non-fatal): %s", exc)
    # First-run seed: same symbols the cron will refresh, but we want hits
    # available immediately so SRCH isn't empty during the first 24h.
    await _index_filings_metadata(meili)


async def _index_filings_metadata(meili) -> int:
    """Re-index filing metadata for the default symbol set. Returns the
    total number of documents pushed to Meili. Called both at startup
    (immediate seed) and from the daily cron."""
    edgar = SecEdgarSource()
    total = 0
    for sym in FILINGS_SEED_SYMBOLS:
        try:
            filings = await edgar.recent_filings(sym, limit=10)
            if filings:
                indexed = await meili.index_filings_metadata(sym, filings)
                total += int(indexed or 0)
        except Exception as exc:
            logger.debug("filings index failed for %s: %s", sym, exc)
    return total


async def _filings_indexer_cron() -> None:
    """Daily background indexer for the default symbol set.

    Sleeps first so the immediate-seed task in `_bootstrap_search_and_sql`
    has finished — re-running the same indexing back-to-back is wasteful
    and would race on the same documents.
    """
    meili = get_meilisearch()
    while True:
        try:
            await asyncio.sleep(FILINGS_INDEX_INTERVAL_SECONDS)
            count = await _index_filings_metadata(meili)
            logger.info("filings indexer cron tick", extra={"refreshed": count})
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Log + keep looping. A flaky 24h tick beats a dead task.
            logger.warning("filings indexer cron tick failed: %s", exc)


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan,
    debug=settings.debug,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RequestLoggingMiddleware)

app.include_router(api_router, prefix=settings.api_prefix)


@app.get("/")
async def root() -> dict[str, str]:
    return {
        "name": settings.app_name,
        "status": "ok",
        "docs": "/docs",
        "api_prefix": settings.api_prefix,
        "version": settings.app_version,
    }


_HEALTH_TIMEOUT_SECONDS = 2.0


async def _check_db() -> str:
    """Run `SELECT 1` against the pool with a short timeout. Returns
    "ok" / "degraded". Never raises — degraded state is a return value,
    not an exception, so the health probe always returns 200."""
    if database.pool is None:
        return "degraded"
    try:
        async def _probe() -> None:
            async with database.acquire() as conn:
                await conn.execute("SELECT 1")
        await asyncio.wait_for(_probe(), timeout=_HEALTH_TIMEOUT_SECONDS)
        return "ok"
    except Exception:
        return "degraded"


async def _check_redis() -> str:
    if cache.client is None:
        return "degraded"
    try:
        await asyncio.wait_for(cache.client.ping(), timeout=_HEALTH_TIMEOUT_SECONDS)
        return "ok"
    except Exception:
        return "degraded"


async def _check_meili() -> str:
    try:
        ok = await asyncio.wait_for(get_meilisearch().health(), timeout=_HEALTH_TIMEOUT_SECONDS)
        return "ok" if ok else "degraded"
    except Exception:
        return "degraded"


@app.get("/healthz")
async def healthz() -> dict[str, object]:
    """Liveness + dependency probe.

    Always returns HTTP 200 (Railway's healthcheck just needs *any* 2xx).
    The body reports per-dependency state so an operator can tell
    *which* part of the stack is sick without digging through logs.
    Each probe has a 2s timeout so a totally-frozen dependency can't
    stretch the response time past Railway's 5s probe budget.
    """
    db_status, redis_status, meili_status = await asyncio.gather(
        _check_db(),
        _check_redis(),
        _check_meili(),
    )
    return {
        "status": "ok",
        "db": db_status,
        "redis": redis_status,
        "meilisearch": meili_status,
        "version": settings.app_version,
    }


if __name__ == "__main__":
    import os

    import uvicorn

    # Railway / Heroku / Fly inject $PORT — honour it when present so the
    # container binds to the platform-assigned port. Locally we fall back
    # to settings.port (8000) which docker-compose / .env can override.
    port = int(os.environ.get("PORT", settings.port))
    uvicorn.run(
        "backend.main:app",
        host="0.0.0.0",
        port=port,
        reload=settings.debug,
    )
