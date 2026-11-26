"""Application configuration, read from environment variables / `.env`.

Only DATABASE_URL is required to boot. Integrations (Claude, Supabase) are
optional here and checked by the features that use them.
"""

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from app.core.paths import BACKEND_DIR, REPO_ROOT

# Repo-root .env first, then backend/.env (later files win).
_ENV_FILES = (REPO_ROOT / ".env", BACKEND_DIR / ".env")


def normalize_database_url(url: str) -> str:
    """Return the asyncpg form of a Postgres URL.

    Accepts postgres://, postgresql://, postgresql+psycopg2:// and
    postgresql+asyncpg:// (Supabase hands out the bare forms).
    """
    for prefix in (
        "postgresql+asyncpg://",
        "postgresql+psycopg2://",
        "postgresql://",
        "postgres://",
    ):
        if url.startswith(prefix):
            return "postgresql+asyncpg://" + url[len(prefix) :]
    raise ValueError("DATABASE_URL must be a PostgreSQL URL")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ENV_FILES, env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    app_name: str = "AI Job Hunter API"
    app_version: str = "0.3.0"
    app_env: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    log_json: bool | None = None  # default: JSON in production only
    api_v1_prefix: str = "/api/v1"
    docs_enabled: bool = True

    # Single-user auth. "none": every request acts as the owner (loopback only).
    # "api_key": requests must send X-API-Key or `Authorization: Bearer <key>`.
    auth_mode: Literal["none", "api_key"] = "none"
    api_key: SecretStr | None = None
    owner_name: str = "owner"
    # Bind address. With AUTH_MODE=none it must be loopback (enforced below).
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

    @model_validator(mode="after")
    def _check_auth(self) -> Settings:
        if self.auth_mode == "api_key":
            key = self.api_key.get_secret_value() if self.api_key else ""
            if len(key) < 32:
                raise ValueError("AUTH_MODE=api_key needs API_KEY of at least 32 characters")
        elif not self.is_loopback_host:
            raise ValueError(
                "AUTH_MODE=none only allows BACKEND_HOST=127.0.0.1/localhost/::1; "
                "set AUTH_MODE=api_key to listen on other interfaces"
            )
        return self

    @property
    def is_loopback_host(self) -> bool:
        return self.backend_host in {"127.0.0.1", "localhost", "::1"}

    @property
    def json_logs(self) -> bool:
        return self.is_production if self.log_json is None else self.log_json

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
