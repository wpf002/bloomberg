from functools import lru_cache
from typing import List

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

    host: str = "0.0.0.0"
    port: int = 8000

    postgres_user: str = "bloomberg"
    postgres_password: str = "bloomberg"
    postgres_db: str = "bloomberg"
    postgres_host: str = "localhost"
    postgres_port: int = 5432

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
    jwt_secret: str | None = None
    jwt_algorithm: str = "HS256"
    jwt_ttl_hours: int = 24 * 30  # 30 days
    session_cookie_name: str = "bt_session"

    # Meilisearch (filings full-text index).
    meilisearch_url: str = "http://meilisearch:7700"
    meilisearch_master_key: str = "bt-meili-dev-key"

    # /api/sql safety rails.
    sql_query_max_rows: int = 5000
    sql_query_timeout_seconds: float = 8.0

    risk_free_rate: float = 0.045
    default_cache_ttl: int = 60
    rss_timeout_seconds: float = 6.0

    cors_origins: List[str] = Field(
        default_factory=lambda: [
            "http://localhost:5173",
            "http://localhost:3000",
            "http://127.0.0.1:5173",
        ]
    )

    @property
    def postgres_dsn(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def redis_url(self) -> str:
        auth = f":{self.redis_password}@" if self.redis_password else ""
        return f"redis://{auth}{self.redis_host}:{self.redis_port}/{self.redis_db}"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
