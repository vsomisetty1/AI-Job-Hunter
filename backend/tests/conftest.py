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
