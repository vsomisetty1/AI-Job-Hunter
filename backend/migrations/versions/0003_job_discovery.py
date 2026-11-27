"""Job discovery: job content hash and expiry time, discovery_runs table.

Executes the FROZEN snapshot migrations/sql/0003_job_discovery.sql.

Revision ID: 0003
Revises: 0002
"""

from pathlib import Path

from alembic import context, op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

SQL_FILE = Path(__file__).resolve().parents[1] / "sql" / "0003_job_discovery.sql"


def upgrade() -> None:
    if context.is_offline_mode():
        raise RuntimeError("Offline (--sql) mode is not supported; run against a database.")
    op.get_bind().exec_driver_sql(SQL_FILE.read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS discovery_runs")
    op.execute(
        """
        ALTER TABLE jobs
            DROP CONSTRAINT ck_jobs_content_hash,
            DROP CONSTRAINT ck_jobs_expired_at,
            DROP COLUMN content_hash,
            DROP COLUMN expired_at
        """
    )
