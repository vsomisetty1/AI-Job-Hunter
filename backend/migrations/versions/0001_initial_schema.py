"""Initial schema: all application tables.

Executes the FROZEN snapshot migrations/sql/0001_initial.sql. Never edit
that file once a database has run it: add a new revision instead.
backend/schema.sql is the human-readable reference for the current head;
tests/unit/test_schema_sql.py keeps the two identical until revision 0002
exists (then update that test to compare against the migrated head).

Revision ID: 0001
Revises:
"""
from pathlib import Path

from alembic import context, op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

SQL_FILE = Path(__file__).resolve().parents[1] / "sql" / "0001_initial.sql"

# Reverse dependency order
TABLES = [
    "llm_cache_entries",
    "browser_sessions",
    "settings",
    "agent_runs",
    "application_answers",
    "application_events",
    "applications",
    "cover_letters",
    "job_scores",
    "resume_versions",
    "jobs",
    "companies",
    "resumes",
    "candidate_profiles",
]


def upgrade() -> None:
    if context.is_offline_mode():
        raise RuntimeError("Offline (--sql) mode is not supported; run against a database.")
    op.get_bind().exec_driver_sql(SQL_FILE.read_text(encoding="utf-8"))


def downgrade() -> None:
    for table in TABLES:
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
    op.execute("DROP FUNCTION IF EXISTS set_updated_at() CASCADE")
