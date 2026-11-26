"""Run migrations against a throwaway Postgres (set TEST_DATABASE_URL).

WARNING: downgrade drops all tables in that database.
"""
import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("alembic")
pytest.importorskip("psycopg2")

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import create_engine, inspect, text  # noqa: E402
from sqlalchemy.exc import IntegrityError  # noqa: E402

from tests.conftest import BACKEND_DIR  # noqa: E402

EXPECTED = {
    "candidate_profiles", "resumes", "resume_versions", "jobs", "job_scores",
    "applications", "application_answers", "cover_letters", "agent_runs",
    "settings", "browser_sessions", "llm_cache",
}  # fmt: skip


@pytest.fixture()
def engine(test_database_url, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", test_database_url)
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    eng = create_engine(
        test_database_url.replace("postgresql+asyncpg://", "postgresql+psycopg2://")
    )
    yield eng, cfg
    eng.dispose()


def test_upgrade_creates_tables_and_settings_row(engine):
    eng, _ = engine
    assert EXPECTED <= set(inspect(eng).get_table_names())
    with eng.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM settings")).scalar() == 1


def test_downgrade_then_upgrade_roundtrip(engine):
    eng, cfg = engine
    command.downgrade(cfg, "base")
    assert not (EXPECTED & set(inspect(eng).get_table_names()))
    command.upgrade(cfg, "head")
    assert EXPECTED <= set(inspect(eng).get_table_names())


def test_constraints_reject_bad_data(engine):
    eng, _ = engine
    bad = [
        "INSERT INTO jobs (source, external_id, company, company_slug, title, url, dedup_key, remote_type)"
        " VALUES ('greenhouse','1','Acme','acme','Role','http://x/1', repeat('a',64), 'moon')",
        "INSERT INTO settings (id) VALUES (2)",
        "INSERT INTO candidate_profiles (full_name, years_experience) VALUES ('A', 99)",
    ]
    for stmt in bad:
        with pytest.raises(IntegrityError):
            with eng.begin() as conn:
                conn.execute(text(stmt))


def test_job_dedup_unique_constraints(engine):
    eng, _ = engine
    ins = (
        "INSERT INTO jobs (source, external_id, company, company_slug, title, url, dedup_key)"
        " VALUES ('lever','42','Acme','acme','Role', :url, repeat('b',64))"
    )
    with eng.begin() as conn:
        conn.execute(text(ins), {"url": "http://x/a"})
    with pytest.raises(IntegrityError):
        with eng.begin() as conn:
            conn.execute(text(ins), {"url": "http://x/b"})  # same source+external_id
