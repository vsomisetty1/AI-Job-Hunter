"""Initial schema: all application tables.

Executes backend/schema.sql so the migration and the schema file can
never drift apart.

Revision ID: 0001
Revises:
"""
from pathlib import Path

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

SCHEMA_FILE = Path(__file__).resolve().parents[2] / "schema.sql"

# Reverse dependency order
TABLES = [
    "llm_cache",
    "browser_sessions",
    "settings",
    "agent_runs",
    "application_answers",
    "applications",
    "cover_letters",
    "job_scores",
    "resume_versions",
    "jobs",
    "resumes",
    "candidate_profiles",
]


def upgrade() -> None:
    sql = SCHEMA_FILE.read_text(encoding="utf-8")
    op.get_bind().exec_driver_sql(sql)


def downgrade() -> None:
    for table in TABLES:
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
    op.execute("DROP FUNCTION IF EXISTS set_updated_at() CASCADE")
