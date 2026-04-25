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
    yield
    try:
        await alert_engine.stop()
        await streamer.stop()
    except Exception as exc:
        logger.warning("Stream/alert background tasks shutdown error: %s", exc)
    await database.disconnect()
    await cache.disconnect()


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
    # Seed filings metadata for the default symbol set so the SRCH panel
    # has something to return on a fresh deployment. Body indexing stays
    # opt-in (it fetches the full EDGAR document per filing, slow).
    try:
        edgar = SecEdgarSource()
        seed_symbols = ["AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "GOOGL", "META", "QQQ"]
        for sym in seed_symbols:
            try:
                filings = await edgar.recent_filings(sym, limit=10)
                if filings:
                    await meili.index_filings_metadata(sym, filings)
            except Exception as exc:
                logger.debug("filings seed failed for %s: %s", sym, exc)
    except Exception as exc:
        logger.warning("filings seed bootstrap failed (non-fatal): %s", exc)


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
