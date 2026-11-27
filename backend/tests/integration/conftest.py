"""Fixtures for API tests against a real, migrated Postgres (TEST_DATABASE_URL).

Each test runs inside an outer transaction that is rolled back, so tests
never see each other's writes. The request session joins it with SAVEPOINTs,
so the app's own commit/rollback logic still runs for real.
"""

import pytest
from alembic import command
from alembic.config import Config

from app.core.config import normalize_database_url
from app.core.database import configure_database, dispose_engine
from app.dependencies import get_db
from tests.conftest import BACKEND_DIR

# Emptied around each test, in FK order (jobs before companies).
USER_TABLES = (
    "candidate_profiles", "agent_runs", "llm_cache_entries", "discovery_runs", "jobs", "companies",
)  # fmt: skip


@pytest.fixture(scope="session")
def migrated_db_url(test_database_url):
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    mp = pytest.MonkeyPatch()
    mp.setenv("DATABASE_URL", test_database_url)
    try:
        command.upgrade(cfg, "head")
    finally:
        mp.undo()
    return normalize_database_url(test_database_url)


@pytest.fixture()
def claude():
    """Fake Claude: tests queue responses on it (see tests/fakes.py)."""
    from tests.fakes import FakeAnthropic

    return FakeAnthropic()


@pytest.fixture()
async def db_conn(migrated_db_url, make_app):
    """One connection inside a transaction that is rolled back after the test."""
    from app.core.config import Settings

    settings = Settings(_env_file=None, database_url=migrated_db_url, app_env="test")
    engine = configure_database(settings)
    conn = await engine.connect()
    outer = await conn.begin()
    # Start every test from empty user data (inside the rolled-back transaction).
    from sqlalchemy import text

    for table in USER_TABLES:
        await conn.execute(text(f"DELETE FROM {table}"))
    try:
        yield conn
    finally:
        await outer.rollback()
        await conn.close()
        await dispose_engine()


@pytest.fixture()
def build_db_app(make_app, migrated_db_url, db_conn):
    """App whose request sessions AND background sessions share the test transaction."""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    def _build(**kwargs):
        sm = async_sessionmaker(
            bind=db_conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
        )
        app = make_app(database_url=migrated_db_url, sessionmaker=sm, **kwargs)

        async def _get_db():
            async with sm() as session:
                try:
                    yield session
                    await session.commit()
                except BaseException:
                    await session.rollback()
                    raise

        app.dependency_overrides[get_db] = _get_db
        app.state.test_connection = db_conn
        return app

    return _build


@pytest.fixture()
def db_app(build_db_app):
    return build_db_app()


@pytest.fixture()
async def build_live_app(make_app, migrated_db_url):
    """App on the real connection pool (commits for real), for flows with
    concurrent background work. User tables are emptied before and after."""
    from sqlalchemy import text

    from app.core.config import Settings
    from app.core.database import get_engine, get_sessionmaker

    configure_database(Settings(_env_file=None, database_url=migrated_db_url, app_env="test"))

    async def clean() -> None:
        async with get_engine().begin() as conn:
            for table in USER_TABLES:
                await conn.execute(text(f"DELETE FROM {table}"))

    await clean()
    apps = []

    def _build(**kwargs):
        app = make_app(database_url=migrated_db_url, sessionmaker=get_sessionmaker(), **kwargs)
        apps.append(app)
        return app

    try:
        yield _build
    finally:
        for app in apps:
            await app.state.task_manager.shutdown(timeout=30)
        await clean()
        await dispose_engine()
