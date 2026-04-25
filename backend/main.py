import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import api_router
from .core.alerts import engine as alert_engine
from .core.config import settings
from .core.database import cache, database
from .core.schema import ensure_schema
from .core.sql_engine import engine as sql_engine
from .core.streaming import streamer
from .data.sources import SecEdgarSource, get_meilisearch

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
)
logger = logging.getLogger("bloomberg-terminal")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting %s (%s)", settings.app_name, settings.app_env)
    try:
        await database.connect()
        await ensure_schema()
    except Exception as exc:
        logger.warning("Postgres unavailable at startup: %s", exc)
    try:
        await cache.connect()
    except Exception as exc:
        logger.warning("Redis unavailable at startup: %s", exc)
    try:
        await streamer.start()
        await alert_engine.start()
    except Exception as exc:
        logger.warning("Stream/alert background tasks failed to start: %s", exc)
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
        logger.warning("Stream/alert background tasks shutdown error: %s", exc)
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
            logger.info("filings indexer cron: refreshed %d documents", count)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Log + keep looping. A flaky 24h tick beats a dead task.
            logger.warning("filings indexer cron tick failed: %s", exc)


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
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

app.include_router(api_router, prefix=settings.api_prefix)


@app.get("/")
async def root() -> dict[str, str]:
    return {
        "name": settings.app_name,
        "status": "ok",
        "docs": "/docs",
        "api_prefix": settings.api_prefix,
    }


@app.get("/healthz")
async def healthz() -> dict[str, object]:
    postgres_ok = database.pool is not None
    redis_ok = cache.client is not None
    meili_ok = False
    try:
        meili_ok = await get_meilisearch().health()
    except Exception:
        meili_ok = False
    return {
        "status": "ok",
        "postgres": postgres_ok,
        "redis": redis_ok,
        "meilisearch": meili_ok,
        "env": settings.app_env,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "backend.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )
