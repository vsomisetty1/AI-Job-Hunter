"""Resume intelligence: resume versions (original/parsed/tailored), parse and
inference status.

Executes the FROZEN snapshot migrations/sql/0002_resume_intelligence.sql.

Revision ID: 0002
Revises: 0001
"""

from pathlib import Path

from alembic import context, op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

SQL_FILE = Path(__file__).resolve().parents[1] / "sql" / "0002_resume_intelligence.sql"


def upgrade() -> None:
    if context.is_offline_mode():
        raise RuntimeError("Offline (--sql) mode is not supported; run against a database.")
    op.get_bind().exec_driver_sql(SQL_FILE.read_text(encoding="utf-8"))


def downgrade() -> None:
    # Untailored versions cannot exist under the 0001 schema (job_id NOT NULL).
    op.execute("DELETE FROM resume_versions WHERE job_id IS NULL")
    op.execute("DROP INDEX IF EXISTS ix_resume_versions_resume_kind")
    op.execute(
        """
        ALTER TABLE resume_versions
            DROP CONSTRAINT uq_resume_versions_resume_version,
            DROP CONSTRAINT ck_resume_versions_kind,
            DROP CONSTRAINT ck_resume_versions_source,
            DROP CONSTRAINT ck_resume_versions_untailored_no_target,
            DROP CONSTRAINT ck_resume_versions_tailored_has_target,
            DROP CONSTRAINT ck_resume_versions_target_role,
            DROP CONSTRAINT ck_resume_versions_target_company,
            DROP COLUMN kind,
            DROP COLUMN source,
            DROP COLUMN target_role,
            DROP COLUMN target_company,
            ALTER COLUMN job_id SET NOT NULL,
            ADD CONSTRAINT uq_resume_versions_resume_job_version
                UNIQUE (resume_id, job_id, version_number)
        """
    )
    op.execute(
        """
        ALTER TABLE resumes
            DROP CONSTRAINT ck_resumes_size,
            DROP CONSTRAINT ck_resumes_parse_status,
            DROP CONSTRAINT ck_resumes_parse_method,
            DROP CONSTRAINT ck_resumes_parsed_has_time,
            DROP COLUMN size_bytes,
            DROP COLUMN parse_status,
            DROP COLUMN parse_method,
            DROP COLUMN parse_error
        """
    )
    op.execute(
        """
        ALTER TABLE candidate_profiles
            DROP CONSTRAINT ck_candidate_profiles_inference_status,
            DROP COLUMN skills,
            DROP COLUMN inference_status,
            DROP COLUMN inference_error,
            DROP COLUMN inferred_at
        """
    )
