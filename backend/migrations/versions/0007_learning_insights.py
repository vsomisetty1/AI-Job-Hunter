"""Learning and insights: interview events, outcome milestones, company
industry, learning snapshots, recommendation states.

Executes the FROZEN snapshot migrations/sql/0007_learning_insights.sql.

Downgrade drops the new tables and columns; withdrawn applications go back to
'submitted' and outcome events become notes (the old schema has neither).

Revision ID: 0007
Revises: 0006
"""

from pathlib import Path

from alembic import context, op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

SQL_FILE = Path(__file__).resolve().parents[1] / "sql" / "0007_learning_insights.sql"
OLD_STATUSES = "'drafted', 'ready', 'submitted', 'interview', 'rejected', 'offer'"


def upgrade() -> None:
    if context.is_offline_mode():
        raise RuntimeError("Offline (--sql) mode is not supported; run against a database.")
    op.get_bind().exec_driver_sql(SQL_FILE.read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute("DROP TABLE recommendation_states")
    op.execute("DROP TABLE learning_snapshots")
    op.execute("ALTER TABLE companies DROP CONSTRAINT ck_companies_industry, DROP COLUMN industry")
    op.execute("DROP TABLE interview_events")
    op.execute(
        "UPDATE application_events SET event_type = 'note' "
        "WHERE event_type IN ('outcome_recorded', 'outcome_updated', 'outcome_removed')"
    )
    op.execute(
        "UPDATE application_events SET from_status = 'submitted' WHERE from_status = 'withdrawn'"
    )
    op.execute(
        "UPDATE application_events SET to_status = 'submitted' WHERE to_status = 'withdrawn'"
    )
    op.execute(
        f"""
        ALTER TABLE application_events
            DROP CONSTRAINT ck_application_events_type,
            ADD CONSTRAINT ck_application_events_type
                CHECK (event_type IN ('created', 'status_changed', 'approved',
                       'automation_started', 'checkpoint', 'retry', 'needs_manual', 'failed',
                       'submitted', 'note')),
            DROP CONSTRAINT ck_application_events_from_status,
            ADD CONSTRAINT ck_application_events_from_status
                CHECK (from_status IS NULL OR from_status IN ({OLD_STATUSES})),
            DROP CONSTRAINT ck_application_events_to_status,
            ADD CONSTRAINT ck_application_events_to_status
                CHECK (to_status IS NULL OR to_status IN ({OLD_STATUSES}))
        """
    )
    op.execute("UPDATE applications SET status = 'submitted' WHERE status = 'withdrawn'")
    op.execute(
        f"""
        ALTER TABLE applications
            DROP CONSTRAINT ck_applications_outcomes_after_submit,
            DROP COLUMN responded_at,
            DROP COLUMN first_interview_at,
            DROP COLUMN offer_at,
            DROP COLUMN rejected_at,
            DROP COLUMN withdrawn_at,
            DROP CONSTRAINT ck_applications_status,
            ADD CONSTRAINT ck_applications_status CHECK (status IN ({OLD_STATUSES}))
        """
    )
