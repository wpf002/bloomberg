import os
from functools import lru_cache
from typing import List
from urllib.parse import urlparse

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Bloomberg Terminal"
    app_env: str = Field(default="development")
    debug: bool = Field(default=True)
    api_prefix: str = "/api"
    app_version: str = "9.2.0"

    host: str = "0.0.0.0"
    port: int = 8000

    # Railway-style "all-in-one URL" overrides. When set (the managed
    # Postgres / Redis plugins always set them), we parse them and ignore
    # the per-component env vars below. Local docker-compose still uses
    # the per-component vars so dev workflows are unchanged.
    database_url: str | None = None

    postgres_user: str = "bloomberg"
    postgres_password: str = "bloomberg"
    postgres_db: str = "bloomberg"
    postgres_host: str = "localhost"
    postgres_port: int = 5432

    redis_url_override: str | None = Field(default=None, alias="REDIS_URL")
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: str | None = None

    alpaca_api_key: str | None = None
    alpaca_api_secret: str | None = None
    alpaca_base_url: str = "https://paper-api.alpaca.markets"

    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-4-6"

    fred_api_key: str | None = None
    finnhub_api_key: str | None = None
    fmp_api_key: str | None = None
    sec_user_agent: str = "bloomberg-terminal research@example.com"

    # Frontend URL the GitHub OAuth callback should redirect back to after
    # setting the session cookie. Falls back to the Vite dev server.
    frontend_url: str = "http://localhost:5173"

    # GitHub OAuth — register an application at https://github.com/settings/developers
    # with callback URL "<api>/api/auth/github/callback".
    github_client_id: str | None = None
    github_client_secret: str | None = None

    # Session JWT signing. Auto-generated on first boot if unset; persisted
    # tokens become invalid across restarts in that case (acceptable for dev).
    # Railway: set SECRET_KEY (preferred) or JWT_SECRET — we accept either.
    secret_key: str | None = None
    jwt_secret: str | None = None
    jwt_algorithm: str = "HS256"
    jwt_ttl_hours: int = 24 * 30  # 30 days
    session_cookie_name: str = "bt_session"

    # Meilisearch (filings full-text index).
    meilisearch_url: str = "http://meilisearch:7700"
    meilisearch_master_key: str = "bt-meili-dev-key"
    # Railway exposes the Meili key as MEILISEARCH_KEY in some templates;
    # accept that alias as a fallback.
    meilisearch_key: str | None = Field(default=None, alias="MEILISEARCH_KEY")

    # /api/sql safety rails.
    sql_query_max_rows: int = 5000
    sql_query_timeout_seconds: float = 8.0

    # FINRA TRACE corporate bond data — OAuth2 client credentials grant.
    # Free dev account at https://developer.finra.org/. Without these, the
    # /api/fixed_income/trace endpoint returns 503 instead of failing later
    # in the auth handshake.
    finra_api_key: str | None = None
    finra_api_secret: str | None = None

    # V2.3 — Options flow + market data via Massive. Massive serves a
    # Polygon-compatible REST API at api.massive.com — one key covers
    # quotes, aggregates, options snapshots, and the synthetic flow
    # tape we derive from the options snapshot.
    massive_api_key: str | None = None
    massive_base_url: str = "https://api.massive.com"

    # V2.6 — supplemental data sources (all optional; the app falls back
    # to Alpaca / yfinance when these are unset). Massive replaces the
    # legacy Polygon integration — set MASSIVE_API_KEY above.
    alpaca_data_tier: str = "iex"  # "iex" (free) or "premium" (paid SIP+L2)

    risk_free_rate: float = 0.045
    default_cache_ttl: int = 60
    rss_timeout_seconds: float = 6.0

    # Comma-separated list of allowed CORS origins. Empty by default; we
    # always include FRONTEND_URL and the Vite dev origins below.
    cors_origins_extra: str = Field(default="", alias="CORS_ORIGINS")

    @property
    def postgres_dsn(self) -> str:
        # Railway-style DATABASE_URL wins when present (managed Postgres).
        if self.database_url:
            return self.database_url
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def redis_url(self) -> str:
        if self.redis_url_override:
            return self.redis_url_override
        auth = f":{self.redis_password}@" if self.redis_password else ""
        return f"redis://{auth}{self.redis_host}:{self.redis_port}/{self.redis_db}"

    @property
    def parsed_postgres(self) -> dict:
        """Parse DATABASE_URL into asyncpg-compatible kwargs.

        Railway hands us `postgresql://user:pass@host:port/db?sslmode=require`
        — asyncpg wants user/password/host/port/database as separate args.
        """
        if self.database_url:
            u = urlparse(self.database_url)
            return {
                "user": u.username or "postgres",
                "password": u.password or "",
                "host": u.hostname or "localhost",
                "port": u.port or 5432,
                "database": (u.path or "/postgres").lstrip("/"),
            }
        return {
            "user": self.postgres_user,
            "password": self.postgres_password,
            "host": self.postgres_host,
            "port": self.postgres_port,
            "database": self.postgres_db,
        }

    @property
    def signing_secret(self) -> str | None:
        """Either SECRET_KEY (preferred Railway name) or JWT_SECRET."""
        return self.secret_key or self.jwt_secret

    @property
    def meilisearch_secret(self) -> str:
        """MEILISEARCH_KEY wins when set — Railway "Deploy from image"
        templates expose the key under that name. Fall back to
        MEILISEARCH_MASTER_KEY for the original docker-compose setup."""
        return self.meilisearch_key or self.meilisearch_master_key

    @property
    def cors_origins(self) -> List[str]:
        """Always include the Vite dev origins so local dev keeps working
        even when FRONTEND_URL is set to a Railway URL. Also accept extra
        origins from a comma-separated CORS_ORIGINS env var."""
        origins: list[str] = [
            "http://localhost:5173",
            "http://localhost:3000",
            "http://127.0.0.1:5173",
        ]
        if self.frontend_url and self.frontend_url not in origins:
            origins.append(self.frontend_url.rstrip("/"))
        if self.cors_origins_extra:
            for entry in self.cors_origins_extra.split(","):
                entry = entry.strip().rstrip("/")
                if entry and entry not in origins:
                    origins.append(entry)
        return origins


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
