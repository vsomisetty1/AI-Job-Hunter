"""Application configuration, read from environment variables / `.env`.

Only DATABASE_URL is required to boot. Integrations (Claude, Supabase) are
optional here and checked by the features that use them.
"""

from functools import lru_cache
from pathlib import Path
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
    app_version: str = "0.10.0"
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
        default_factory=lambda: ["http://localhost:3000", "http://127.0.0.1:3000"]
    )
    # Host names the API answers to (Host header, port ignored). Blocks DNS
    # rebinding: another site's name pointed at 127.0.0.1 is refused. "*" turns
    # the check off and is only accepted with AUTH_MODE=api_key.
    allowed_hosts: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["localhost", "127.0.0.1", "::1"]
    )
    # Set only inside the container image: the backend binds 0.0.0.0 inside its
    # container, and Compose publishes the port on the host's 127.0.0.1 only, so
    # AUTH_MODE=none stays reachable from this machine alone (ADR-016).
    container_loopback_only: bool = False

    # repr=False: the URL holds the database password; keep it out of reprs and logs.
    database_url: str = Field(repr=False)
    db_pool_size: int = 5
    db_max_overflow: int = 5
    db_echo: bool = False

    # Claude. Without ANTHROPIC_API_KEY the app still works: parsing and
    # profile generation fall back to deterministic results.
    anthropic_api_key: SecretStr | None = None
    claude_model_scoring: str = "claude-haiku-5-5"
    claude_model_writing: str = "claude-sonnet-5-5"
    # Resume parsing fallback, profile inference, career analysis, skill extraction.
    claude_model_analysis: str = "claude-opus-5-5"
    claude_effort_analysis: Literal["low", "medium", "high", "xhigh", "max"] = "low"
    claude_max_retries: int = Field(default=3, ge=0, le=10)
    claude_timeout_seconds: float = Field(default=120.0, gt=0)
    # Server-side refusal fallback (routes a declined request to another model).
    claude_refusal_fallback: bool = True
    # Job scoring with Claude (opt-in in settings; only with an API key). Limits
    # keep cost predictable: a cap per run, a rolling 24-hour cap, and pacing.
    claude_effort_scoring: Literal["low", "medium", "high", "xhigh", "max"] = "low"
    claude_scoring_max_per_run: int = Field(default=25, ge=0, le=500)
    claude_scoring_max_per_day: int = Field(default=100, ge=0, le=5000)
    claude_scoring_per_minute: float = Field(default=10.0, gt=0, le=600)
    llm_cache_ttl_days: int = Field(default=30, ge=0)  # 0 = never expires
    # Superseded/rejected/failed application packages (and the tailored resume
    # and cover letter they created) are deleted after this many days.
    package_retention_days: int = Field(default=90, ge=1)
    # Files no row points to are deleted by the daily sweep once this old.
    orphan_grace_hours: int = Field(default=24, ge=1)
    # agent_runs older than this are deleted by the daily maintenance job.
    agent_run_retention_days: int = Field(default=180, ge=1)

    # Application automation (Phase 8, approval mode only: the app never
    # submits without the user's confirmation).
    automation_enabled: bool = True
    # false shows the browser window (to watch a run or solve a CAPTCHA).
    automation_headless: bool = True
    # A Chromium/Chrome binary to use instead of Playwright's own download.
    automation_browser_path: str | None = None
    automation_slow_mo_ms: int = Field(default=0, ge=0, le=5000)
    automation_navigation_timeout_ms: int = Field(default=45_000, ge=1000)
    automation_action_timeout_ms: int = Field(default=10_000, ge=500)
    # Open forms waiting for review; more runs wait in the queue.
    automation_max_sessions: int = Field(default=2, ge=1, le=10)
    # An open form nobody touched for this long is closed (Retry reopens it).
    automation_session_idle_minutes: int = Field(default=30, ge=1)
    # Automatic attempts for transient failures (crash, timeout, network).
    automation_max_attempts: int = Field(default=2, ge=1, le=5)
    # How long to wait for the site to confirm a submission.
    automation_submit_timeout_seconds: int = Field(default=45, ge=5)

    # Resume uploads
    max_upload_mb: float = Field(default=10.0, gt=0, le=50)
    max_pdf_pages: int = Field(default=20, ge=1, le=200)
    parse_timeout_seconds: float = Field(default=30.0, gt=0)
    parse_memory_limit_mb: int = Field(default=1024, ge=128)
    # "clamd": scan every upload with ClamAV (INSTREAM). Uploads are always
    # structurally checked (see app/documents/validation.py) regardless.
    virus_scanner: Literal["none", "clamd"] = "none"
    clamd_host: str = "127.0.0.1"
    clamd_port: int = 3310
    clamd_timeout_seconds: float = Field(default=30.0, gt=0)

    # File storage. "local" keeps files under LOCAL_STORAGE_DIR; "supabase"
    # uses a private Supabase Storage bucket.
    storage_backend: Literal["local", "supabase"] = "local"
    # A relative path is resolved against backend/ (see local_storage_path), so
    # the app, the backup script and the docs all mean the same folder.
    local_storage_dir: str = "./data/storage"
    supabase_url: str | None = None
    supabase_service_role_key: SecretStr | None = None
    supabase_bucket: str = "job-hunter"

    scheduler_enabled: bool = True
    # Re-filter and re-score stored jobs in the background when the settings
    # or the profile change (otherwise only scheduled runs and "Re-score" do).
    rescore_on_change: bool = True
    discovery_interval_minutes: int = Field(default=360, ge=5)
    # Job boards crawled in parallel, and HTTP behaviour towards them.
    discovery_concurrency: int = Field(default=4, ge=1, le=16)
    connector_timeout_seconds: float = Field(default=30.0, gt=0)
    connector_retry_attempts: int = Field(default=4, ge=1, le=10)

    @field_validator("database_url")
    @classmethod
    def _normalize_db_url(cls, v: str) -> str:
        return normalize_database_url(v.strip())

    @field_validator("cors_origins", "allowed_hosts", mode="before")
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
        else:
            if not (self.is_loopback_host or self.container_loopback_only):
                raise ValueError(
                    "AUTH_MODE=none only allows BACKEND_HOST=127.0.0.1/localhost/::1; "
                    "set AUTH_MODE=api_key to listen on other interfaces"
                )
            if "*" in self.allowed_hosts:
                raise ValueError("ALLOWED_HOSTS=* needs AUTH_MODE=api_key")
        if not self.allowed_hosts:
            raise ValueError("ALLOWED_HOSTS must name at least one host")
        return self

    @model_validator(mode="after")
    def _check_storage(self) -> Settings:
        if self.storage_backend == "supabase" and not (
            self.supabase_url and self.supabase_service_role_key
        ):
            raise ValueError(
                "STORAGE_BACKEND=supabase needs SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY"
            )
        return self

    @property
    def local_storage_path(self) -> Path:
        path = Path(self.local_storage_dir).expanduser()
        return path if path.is_absolute() else (BACKEND_DIR / path).resolve()

    @property
    def max_upload_bytes(self) -> int:
        return int(self.max_upload_mb * 1024 * 1024)

    @property
    def llm_enabled(self) -> bool:
        return bool(self.anthropic_api_key and self.anthropic_api_key.get_secret_value())

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
    return Settings()  # values come from the environment / .env
