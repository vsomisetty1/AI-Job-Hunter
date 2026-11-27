"""Application automation (approval mode): submissions and automation logs.

Executes the FROZEN snapshot migrations/sql/0006_application_automation.sql.

Downgrade drops both tables (screenshot files are left for the orphan sweep).

Revision ID: 0006
Revises: 0005
"""

from pathlib import Path

from alembic import context, op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

SQL_FILE = Path(__file__).resolve().parents[1] / "sql" / "0006_application_automation.sql"


def upgrade() -> None:
    if context.is_offline_mode():
        raise RuntimeError("Offline (--sql) mode is not supported; run against a database.")
    op.get_bind().exec_driver_sql(SQL_FILE.read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute("DROP TABLE automation_logs")
    op.execute("DROP TABLE application_submissions")
