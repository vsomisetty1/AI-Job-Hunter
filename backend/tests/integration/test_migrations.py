"""Migration + schema validation against a throwaway Postgres 15+.

Set TEST_DATABASE_URL to an EMPTY, disposable database, e.g.
  postgresql+psycopg2://jobhunter:change_me@localhost:5432/jobhunter_test
WARNING: these tests run `alembic downgrade base`, which drops all tables.
"""
from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("alembic")
pytest.importorskip("psycopg2")

from alembic import command  # noqa: E402
from alembic.autogenerate import compare_metadata  # noqa: E402
from alembic.config import Config  # noqa: E402
from alembic.migration import MigrationContext  # noqa: E402
from sqlalchemy import create_engine, inspect, text  # noqa: E402

import app.models  # noqa: E402,F401
from app.models.base import Base  # noqa: E402
from tests.conftest import BACKEND_DIR  # noqa: E402

SQL_DIR = BACKEND_DIR / "tests" / "sql"
EXPECTED = set(Base.metadata.tables)


@pytest.fixture()
def db(test_database_url, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", test_database_url)
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    eng = create_engine(test_database_url.replace("+asyncpg", "+psycopg2"))
    yield eng, cfg
    eng.dispose()


def _run_sql_file(eng, name: str):
    sql = (SQL_DIR / name).read_text(encoding="utf-8")
    raw = eng.raw_connection()
    try:
        cur = raw.cursor()
        cur.execute(sql)
        rows = []
        try:
            rows = cur.fetchall()
        except Exception:  # statement had no result set
            pass
        raw.commit()
        return rows
    finally:
        raw.close()


def test_upgrade_creates_all_tables_and_seed_row(db):
    eng, _ = db
    assert EXPECTED <= set(inspect(eng).get_table_names())
    with eng.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM settings")).scalar() == 1


def test_downgrade_then_upgrade_roundtrip(db):
    eng, cfg = db
    command.downgrade(cfg, "base")
    assert not (EXPECTED & set(inspect(eng).get_table_names()))
    command.upgrade(cfg, "head")
    assert EXPECTED <= set(inspect(eng).get_table_names())


def test_catalog_validation_has_no_findings(db):
    eng, _ = db
    sql = (SQL_DIR / "validate_catalog.sql").read_text(encoding="utf-8")
    raw = eng.raw_connection()
    try:
        cur = raw.cursor()
        cur.execute(sql)
        assert cur.fetchall() == []
    finally:
        raw.close()


def test_behavioural_constraints(db):
    eng, _ = db
    rows = _run_sql_file(eng, "behavior.sql")
    assert rows and rows[-1][0] == "behavior checks passed"


def test_orm_matches_database_no_structural_drift(db):
    """No table or column may exist on only one side (ORM vs migrated DB)."""
    eng, _ = db
    with eng.connect() as conn:
        diffs = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    structural = {"add_table", "remove_table", "add_column", "remove_column"}
    flat = []
    for d in diffs:
        flat += d if isinstance(d, list) else [d]
    bad = [d for d in flat if d[0] in structural]
    assert not bad, bad
