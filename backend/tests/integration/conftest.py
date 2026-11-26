"""Fixtures for API tests against a real, migrated Postgres (TEST_DATABASE_URL).

Each test runs inside an outer transaction that is rolled back, so tests
never see each other's writes. The request session joins it with SAVEPOINTs,
so the app's own commit/rollback logic still runs for real.
"""

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import normalize_database_url
from app.core.database import configure_database, dispose_engine
from app.core.dependencies import get_db
from tests.conftest import BACKEND_DIR


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
async def db_app(make_app, migrated_db_url):
    app = make_app(database_url=migrated_db_url)
    engine = configure_database(app.state.settings)
    conn = await engine.connect()
    outer = await conn.begin()

    async def _get_db():
        async with AsyncSession(
            bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
        ) as session:
            try:
                yield session
                await session.commit()
            except BaseException:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = _get_db
    app.state.test_connection = conn
    try:
        yield app
    finally:
        await outer.rollback()
        await conn.close()
        await dispose_engine()
