import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import api_router
from .core.alerts import engine as alert_engine
from .core.config import settings
from .core.database import cache, database
from .core.streaming import streamer

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
    yield
    try:
        await alert_engine.stop()
        await streamer.stop()
    except Exception as exc:
        logger.warning("Stream/alert background tasks shutdown error: %s", exc)
    await database.disconnect()
    await cache.disconnect()


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
    return {
        "status": "ok",
        "postgres": postgres_ok,
        "redis": redis_ok,
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
