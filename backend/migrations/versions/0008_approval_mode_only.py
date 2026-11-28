"""Approval mode only: settings and applications can no longer store
AUTONOMOUS_MODE (Phase 10, ADR-016).

Executes the FROZEN snapshot migrations/sql/0008_approval_mode_only.sql.

Downgrade restores the 0007 constraints (allowing AUTONOMOUS_MODE again);
no data changes.

Revision ID: 0008
Revises: 0007
"""

from pathlib import Path

from alembic import context, op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

SQL_FILE = Path(__file__).resolve().parents[1] / "sql" / "0008_approval_mode_only.sql"
BOTH = "application_mode IN ('APPROVAL_MODE', 'AUTONOMOUS_MODE')"


def upgrade() -> None:
    if context.is_offline_mode():
        raise RuntimeError("Offline (--sql) mode is not supported; run against a database.")
    op.get_bind().exec_driver_sql(SQL_FILE.read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute(
        f"ALTER TABLE settings DROP CONSTRAINT ck_settings_mode, "
        f"ADD CONSTRAINT ck_settings_mode CHECK ({BOTH})"
    )
    op.execute(
        f"ALTER TABLE applications DROP CONSTRAINT ck_applications_mode, "
        f"ADD CONSTRAINT ck_applications_mode CHECK ({BOTH})"
    )
