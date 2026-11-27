"""Migration + schema validation against a throwaway Postgres 15+.

Set TEST_DATABASE_URL to an EMPTY, disposable database, e.g.
  postgresql+psycopg2://jobhunter:change_me@localhost:5432/jobhunter_test
WARNING: these tests run `alembic downgrade base`, which drops all tables.
"""

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("alembic")
pytest.importorskip("psycopg2")

import psycopg2
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, make_url, text

import app.models  # noqa: F401
from app.models.base import Base
from tests.conftest import BACKEND_DIR

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
        except psycopg2.ProgrammingError:  # statement had no result set
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


def test_orm_matches_database_exactly(db):
    """ORM vs migrated DB: no difference in tables, columns, types, nullability,
    server defaults, indexes, unique constraints or foreign keys."""
    eng, _ = db
    with eng.connect() as conn:
        ctx = MigrationContext.configure(
            conn, opts={"compare_type": True, "compare_server_default": True}
        )
        diffs = compare_metadata(ctx, Base.metadata)
    assert diffs == [], diffs


# ---------------------------------------------------------------------------
# schema.sql must describe exactly what the migrations build.
# ---------------------------------------------------------------------------
_CATALOG_QUERIES = {
    "columns": """
        SELECT table_name, column_name, udt_name, is_nullable, coalesce(column_default, '')
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name <> 'alembic_version'
    """,
    "constraints": """
        SELECT conrelid::regclass::text, conname, pg_get_constraintdef(oid)
        FROM pg_constraint
        WHERE connamespace = 'public'::regnamespace
          AND conrelid::regclass::text <> 'alembic_version'
    """,
    "indexes": """
        SELECT tablename, indexname, indexdef FROM pg_indexes
        WHERE schemaname = 'public' AND tablename <> 'alembic_version'
    """,
    "triggers": """
        SELECT tgrelid::regclass::text, tgname, pg_get_triggerdef(oid)
        FROM pg_trigger WHERE NOT tgisinternal
    """,
    "functions": """
        SELECT proname, prosrc FROM pg_proc
        WHERE pronamespace = 'public'::regnamespace
    """,
}


def _catalog(eng) -> dict[str, set[tuple]]:
    with eng.connect() as conn:
        return {k: {tuple(r) for r in conn.execute(text(q))} for k, q in _CATALOG_QUERIES.items()}


def test_reference_schema_sql_matches_migrated_head(db, test_database_url):
    """Build schema.sql in a scratch database and compare catalogs with head."""
    migrated, _ = db
    url = make_url(test_database_url.replace("+asyncpg", "+psycopg2"))
    ref_name = f"{url.database}_schema_ref"
    admin = create_engine(url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{ref_name}"'))
        conn.execute(text(f'CREATE DATABASE "{ref_name}"'))
    ref = create_engine(url.set(database=ref_name))
    try:
        raw = ref.raw_connection()
        try:
            raw.cursor().execute((BACKEND_DIR / "schema.sql").read_text(encoding="utf-8"))
            raw.commit()
        finally:
            raw.close()
        expected, actual = _catalog(ref), _catalog(migrated)
        for kind in _CATALOG_QUERIES:
            missing = sorted(expected[kind] - actual[kind])
            extra = sorted(actual[kind] - expected[kind])
            assert not missing and not extra, (
                f"{kind}: only in schema.sql={missing} only in DB={extra}"
            )
    finally:
        ref.dispose()
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{ref_name}"'))
        admin.dispose()


def test_0002_renumbers_versions_and_downgrade_removes_untailored(db):
    """Data written under 0001 survives 0002; 0002-only rows are dropped on downgrade."""
    eng, cfg = db
    command.downgrade(cfg, "0001")
    with eng.begin() as conn:
        p = conn.execute(
            text("INSERT INTO candidate_profiles (full_name) VALUES ('A') RETURNING id")
        ).scalar()
        r = conn.execute(
            text(
                "INSERT INTO resumes (profile_id, filename, file_type, storage_path, content_hash) "
                "VALUES (:p, 'cv.pdf', 'pdf', 'r/1.pdf', repeat('a', 64)) RETURNING id"
            ),
            {"p": p},
        ).scalar()
        c = conn.execute(
            text(
                "INSERT INTO companies (name, source, slug) "
                "VALUES ('Acme', 'lever', 'acme') RETURNING id"
            )
        ).scalar()
        for n in (1, 2):
            j = conn.execute(
                text(
                    "INSERT INTO jobs (company_id, external_id, title, url, dedup_key) "
                    "VALUES (:c, :n, 'Eng', :u, repeat('b', 64)) RETURNING id"
                ),
                {"c": c, "n": str(n), "u": f"https://x.test/{n}"},
            ).scalar()
            # Same version_number 1 for two jobs: legal under 0001.
            conn.execute(
                text("INSERT INTO resume_versions (resume_id, job_id) VALUES (:r, :j)"),
                {"r": r, "j": j},
            )

    command.upgrade(cfg, "head")
    with eng.begin() as conn:
        rows = conn.execute(
            text("SELECT kind, source, version_number FROM resume_versions ORDER BY version_number")
        ).all()
        assert [tuple(x) for x in rows] == [
            ("tailored", "tailoring", 1),
            ("tailored", "tailoring", 2),
        ]
        conn.execute(
            text(
                "INSERT INTO resume_versions (resume_id, kind, source, version_number) "
                "VALUES (:r, 'parsed', 'parser', 3)"
            ),
            {"r": r},
        )

    command.downgrade(cfg, "0001")
    with eng.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM resume_versions")).scalar() == 2
    command.upgrade(cfg, "head")
    with eng.begin() as conn:  # leave no user data behind for other tests
        for table in ("candidate_profiles", "jobs", "companies"):  # FK order
            conn.execute(text(f"DELETE FROM {table}"))


def test_0004_keeps_existing_claude_scores_and_downgrades_cleanly(db):
    """Old rows (one per prompt version) collapse to the newest and become 'claude';
    downgrading drops what the old schema cannot hold."""
    eng, cfg = db
    command.downgrade(cfg, "0003")
    h = "a" * 64
    with eng.begin() as conn:
        p = conn.execute(
            text("INSERT INTO candidate_profiles (full_name) VALUES ('X') RETURNING id")
        ).scalar()
        c = conn.execute(
            text(
                "INSERT INTO companies (name, source, slug) VALUES ('A', 'lever', 'a') RETURNING id"
            )
        ).scalar()
        j = conn.execute(
            text("INSERT INTO jobs (company_id, external_id, title, url, dedup_key) "
                 "VALUES (:c, '1', 'Eng', 'https://x.test/1', :h) RETURNING id"),
            {"c": c, "h": h},
        ).scalar()  # fmt: skip
        for version, at in (("v1", "2026-01-01"), ("v2", "2026-02-01")):
            conn.execute(
                text("INSERT INTO job_scores (job_id, profile_id, overall_score, "
                     "interview_probability, salary_score, growth_score, company_score, model, "
                     "prompt_version, created_at) VALUES (:j, :p, 50, 1, 1, 1, 1, 'm', :v, :at)"),
                {"j": j, "p": p, "v": version, "at": at},
            )  # fmt: skip
    command.upgrade(cfg, "head")
    with eng.begin() as conn:
        rows = conn.execute(text("SELECT scoring_method, prompt_version FROM job_scores")).all()
        assert [tuple(r) for r in rows] == [("claude", "v2")]
        conn.execute(
            text("INSERT INTO job_scores (job_id, profile_id, overall_score) VALUES (:j, :p, 70)"),
            {"j": j, "p": p},
        )
    command.downgrade(cfg, "0003")
    with eng.connect() as conn:
        rows = conn.execute(text("SELECT prompt_version FROM job_scores")).all()
        assert [tuple(r) for r in rows] == [("v2",)]  # the rule-based row is gone
    command.upgrade(cfg, "head")


def test_0005_downgrade_keeps_the_newest_cover_letter_and_drops_packages(db):
    eng, cfg = db
    with eng.begin() as conn:
        p = conn.execute(
            text("INSERT INTO candidate_profiles (full_name) VALUES ('X') RETURNING id")
        ).scalar()
        c = conn.execute(
            text(
                "INSERT INTO companies (name, source, slug) VALUES ('A', 'lever', 'a') RETURNING id"
            )
        ).scalar()
        j = conn.execute(
            text(
                "INSERT INTO jobs (company_id, external_id, title, url, dedup_key) "
                "VALUES (:c, '1', 'Eng', 'https://x.test/1', :h) RETURNING id"
            ),
            {"c": c, "h": "b" * 64},
        ).scalar()
        for n in (1, 2):
            conn.execute(
                text(
                    "INSERT INTO cover_letters (job_id, profile_id, content, version_number) "
                    "VALUES (:j, :p, :t, :n)"
                ),
                {"j": j, "p": p, "t": f"Draft {n}", "n": n},
            )
        pkg = conn.execute(
            text(
                "INSERT INTO application_packages (job_id, profile_id) VALUES (:j, :p) RETURNING id"
            ),
            {"j": j, "p": p},
        ).scalar()
        conn.execute(
            text(
                "INSERT INTO application_answers (package_id, question, question_hash, answer, "
                "source) VALUES (:k, 'Q', :h, 'A', 'rules')"
            ),
            {"k": pkg, "h": "c" * 64},
        )
    command.downgrade(cfg, "0004")
    with eng.connect() as conn:
        assert [tuple(r) for r in conn.execute(text("SELECT content FROM cover_letters"))] == [
            ("Draft 2",)
        ]
        assert conn.execute(text("SELECT count(*) FROM application_answers")).scalar() == 0
        assert "application_packages" not in inspect(eng).get_table_names()
    command.upgrade(cfg, "head")


def test_0006_enforces_approval_mode_and_user_confirmation(db):
    """The database itself refuses autonomous runs, a submission without the
    user's confirmation, and two active runs for one application."""
    import sqlalchemy.exc

    eng, cfg = db
    with eng.begin() as conn:
        p = conn.execute(
            text("INSERT INTO candidate_profiles (full_name) VALUES ('X') RETURNING id")
        ).scalar()
        c = conn.execute(
            text(
                "INSERT INTO companies (name, source, slug) VALUES ('A', 'lever', 'a') RETURNING id"
            )
        ).scalar()
        j = conn.execute(
            text(
                "INSERT INTO jobs (company_id, external_id, title, url, dedup_key) "
                "VALUES (:c, '1', 'Eng', 'https://x.test/1', :h) RETURNING id"
            ),
            {"c": c, "h": "d" * 64},
        ).scalar()
        a = conn.execute(
            text("INSERT INTO applications (job_id, profile_id) VALUES (:j, :p) RETURNING id"),
            {"j": j, "p": p},
        ).scalar()
    insert = (
        "INSERT INTO application_submissions (application_id, platform, apply_url{cols}) "
        "VALUES (:a, 'lever', 'https://jobs.lever.co/a/1/apply'{vals}) RETURNING id"
    )

    def attempt(cols: str = "", vals: str = "", **params) -> None:
        with eng.begin() as conn:
            conn.execute(text(insert.format(cols=cols, vals=vals)), {"a": a, **params})

    for cols, vals in (
        (", mode", ", 'AUTONOMOUS_MODE'"),  # not built: refused
        (", status, submitted_at", ", 'submitted', now()"),  # never without confirmation
        (", status", ", 'failed'"),  # a failure records when and why
    ):
        with pytest.raises(sqlalchemy.exc.IntegrityError):
            attempt(cols, vals)
    attempt()  # queued
    with pytest.raises(sqlalchemy.exc.IntegrityError):
        attempt()  # a second active run for the same application
    attempt(", status, cancelled_at", ", 'cancelled', now()")  # finished runs may pile up
    attempt(", status, confirmed_at, submitted_at", ", 'submitted', now(), now()")
    with eng.begin() as conn:
        sid = conn.execute(text("SELECT id FROM application_submissions LIMIT 1")).scalar()
        conn.execute(
            text("INSERT INTO automation_logs (submission_id, message) VALUES (:s, 'opened')"),
            {"s": sid},
        )
    command.downgrade(cfg, "0005")
    assert "application_submissions" not in inspect(eng).get_table_names()
    assert "automation_logs" not in inspect(eng).get_table_names()
    command.upgrade(cfg, "head")


def test_0007_outcomes_rules_and_downgrade(db):
    """Outcomes need a sent application; responses and offers are completed events;
    downgrade keeps withdrawn applications as submitted and drops the new tables."""
    import sqlalchemy.exc

    eng, cfg = db
    with eng.begin() as conn:
        p = conn.execute(
            text("INSERT INTO candidate_profiles (full_name) VALUES ('X') RETURNING id")
        ).scalar()
        c = conn.execute(
            text(
                "INSERT INTO companies (name, source, slug) VALUES ('A', 'lever', 'a') RETURNING id"
            )
        ).scalar()
        jobs = [
            conn.execute(
                text(
                    "INSERT INTO jobs (company_id, external_id, title, url, dedup_key) "
                    "VALUES (:c, :e, 'Eng', :u, :h) RETURNING id"
                ),
                {"c": c, "e": str(n), "u": f"https://x.test/{n}", "h": str(n) * 64},
            ).scalar()
            for n in (1, 2)
        ]
        sent = conn.execute(
            text(
                "INSERT INTO applications (job_id, profile_id, status, submitted_at, "
                "withdrawn_at) VALUES (:j, :p, 'withdrawn', now(), now()) RETURNING id"
            ),
            {"j": jobs[0], "p": p},
        ).scalar()
        draft = conn.execute(
            text("INSERT INTO applications (job_id, profile_id) VALUES (:j, :p) RETURNING id"),
            {"j": jobs[1], "p": p},
        ).scalar()
        conn.execute(
            text(
                "INSERT INTO interview_events (application_id, stage, status, occurred_at) "
                "VALUES (:a, 'phone_screen', 'scheduled', now())"
            ),
            {"a": sent},
        )
        conn.execute(text("UPDATE companies SET industry = 'Fintech' WHERE id = :c"), {"c": c})

    bad = (
        ("UPDATE applications SET offer_at = now() WHERE id = :a", {"a": draft}),
        ("INSERT INTO interview_events (application_id, stage, status, occurred_at) "
         "VALUES (:a, 'offer', 'scheduled', now())", {"a": sent}),
        ("UPDATE companies SET industry = '  ' WHERE id = :c", {"c": c}),
        ("INSERT INTO recommendation_states (key, status) VALUES ('Bad Key!', 'done')", {}),
    )  # fmt: skip
    for sql, params in bad:
        with pytest.raises(sqlalchemy.exc.IntegrityError), eng.begin() as conn:
            conn.execute(text(sql), params)

    command.downgrade(cfg, "0006")
    with eng.connect() as conn:
        assert (
            conn.execute(
                text("SELECT status FROM applications WHERE id = :a"), {"a": sent}
            ).scalar()
            == "submitted"
        )
    names = inspect(eng).get_table_names()
    assert not {"interview_events", "learning_snapshots", "recommendation_states"} & set(names)
    command.upgrade(cfg, "head")
