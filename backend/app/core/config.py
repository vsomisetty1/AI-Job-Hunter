"""Application configuration, read from environment variables / `.env`.

Only DATABASE_URL is required to boot. Integrations (Claude, Supabase) are
optional here and checked by the features that use them.
"""
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# Repo-root .env first, then backend/.env (later files win).
_BACKEND_DIR = Path(__file__).resolve().parents[2]
_ENV_FILES = (_BACKEND_DIR.parent / ".env", _BACKEND_DIR / ".env")


def normalize_database_url(url: str) -> str:
    """Return the asyncpg form of a Postgres URL.

    Accepts postgres://, postgresql://, postgresql+psycopg2:// and
    postgresql+asyncpg:// (Supabase hands out the bare forms).
    """
    for prefix in ("postgresql+asyncpg://", "postgresql+psycopg2://", "postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+asyncpg://" + url[len(prefix):]
    raise ValueError("DATABASE_URL must be a PostgreSQL URL")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ENV_FILES, env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    app_env: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    # Personal-use app: the API has no auth, so it only listens on loopback.
    backend_host: str = "127.0.0.1"
    backend_port: int = 8000
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3000"]
    )

    database_url: str
    db_pool_size: int = 5
    db_max_overflow: int = 5
    db_echo: bool = False

    anthropic_api_key: str | None = None
    claude_model_scoring: str = "claude-haiku-5-5"
    claude_model_writing: str = "claude-sonnet-5-5"

    supabase_url: str | None = None
    supabase_service_role_key: str | None = None
    supabase_bucket: str = "job-hunter"

    playwright_headless: bool = True
    browser_state_dir: str = "./browser_state"

    scheduler_enabled: bool = True
    discovery_interval_minutes: int = Field(default=360, ge=5)

    @field_validator("database_url")
    @classmethod
    def _normalize_db_url(cls, v: str) -> str:
        return normalize_database_url(v.strip())

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def uses_transaction_pooler(self) -> bool:
        """Supabase's pgbouncer (port 6543) cannot use asyncpg prepared statements."""
        return ":6543/" in self.database_url or "pgbouncer=true" in self.database_url


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  (values come from the environment)
