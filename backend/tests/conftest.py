"""Shared pytest fixtures."""

import os
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
SCHEMA_SQL = BACKEND_DIR / "schema.sql"


@pytest.fixture(scope="session")
def schema_sql() -> str:
    return SCHEMA_SQL.read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def test_database_url() -> str:
    """Disposable Postgres for migration tests (these tests DROP tables).

    Set TEST_DATABASE_URL, e.g.
    postgresql+psycopg2://jobhunter:change_me@localhost:5432/jobhunter_test
    """
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set")
    return url


# ---------------------------------------------------------------------------
# App factory for API tests. Lifespan is not run (httpx's ASGITransport does
# not send lifespan events), so the state it would create is set here with
# the scheduler disabled.
# ---------------------------------------------------------------------------
@pytest.fixture()
def make_app(tmp_path):
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.bootstrap import init_services
    from app.core.config import Settings, get_settings
    from app.main import create_app
    from app.scheduler.background import BackgroundTaskManager
    from app.scheduler.scheduler import SchedulerService
    from app.storage import LocalStorage

    def _make(*, claude=None, sessionmaker=None, http=None, **overrides):
        overrides.setdefault("database_url", "postgresql://u:p@127.0.0.1:1/unused")
        overrides.setdefault("app_env", "test")
        overrides.setdefault("scheduler_enabled", False)
        # Background re-scoring would share the single test connection with the
        # next request; tests that cover it turn it on with the live-pool app.
        overrides.setdefault("rescore_on_change", False)
        settings = Settings(_env_file=None, **overrides)
        app = create_app(settings)
        app.dependency_overrides[get_settings] = lambda: settings
        app.state.task_manager = BackgroundTaskManager()
        app.state.scheduler = SchedulerService(enabled=False)
        init_services(
            app,
            settings,
            sessionmaker=sessionmaker or async_sessionmaker(),  # unbound: no DB in unit tests
            anthropic_client=claude,
            storage=LocalStorage(tmp_path / "storage"),
            http=http,
        )
        return app

    return _make


@pytest.fixture()
def client_for():
    import httpx

    def _client(app):
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
        )

    return _client
