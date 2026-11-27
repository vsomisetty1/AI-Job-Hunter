"""Application packages: package table, tailored-resume change tracking,
versioned cover letters, package answers with evidence, relocation setting.

Executes the FROZEN snapshot migrations/sql/0005_application_packages.sql.

Downgrade drops packages and their answers, and keeps only the newest cover
letter per job and profile (the old schema allows one).

Revision ID: 0005
Revises: 0004
"""

from pathlib import Path

from alembic import context, op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

SQL_FILE = Path(__file__).resolve().parents[1] / "sql" / "0005_application_packages.sql"


def upgrade() -> None:
    if context.is_offline_mode():
        raise RuntimeError("Offline (--sql) mode is not supported; run against a database.")
    op.get_bind().exec_driver_sql(SQL_FILE.read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute("ALTER TABLE settings DROP COLUMN willing_to_relocate")
    op.execute("DELETE FROM application_answers WHERE package_id IS NOT NULL")
    op.execute(
        """
        ALTER TABLE application_answers
            DROP CONSTRAINT uq_application_answers_package_question,
            DROP CONSTRAINT ck_application_answers_source,
            ADD CONSTRAINT ck_application_answers_source
                CHECK (source IN ('profile', 'settings', 'llm', 'user')),
            DROP CONSTRAINT ck_application_answers_answer,
            DROP CONSTRAINT ck_application_answers_evidence_json,
            DROP CONSTRAINT ck_application_answers_one_owner,
            DROP CONSTRAINT fk_application_answers_package_id,
            DROP COLUMN evidence,
            DROP COLUMN package_id,
            ALTER COLUMN application_id SET NOT NULL
        """
    )
    op.execute("DROP TABLE application_packages")
    op.execute(
        """
        DELETE FROM cover_letters a USING cover_letters b
        WHERE a.job_id = b.job_id AND a.profile_id = b.profile_id
          AND a.version_number < b.version_number
        """
    )
    op.execute(
        """
        ALTER TABLE cover_letters
            DROP CONSTRAINT uq_cover_letters_job_profile_version,
            DROP CONSTRAINT ck_cover_letters_generation_json,
            DROP CONSTRAINT ck_cover_letters_method,
            DROP CONSTRAINT ck_cover_letters_word_count,
            DROP CONSTRAINT ck_cover_letters_version,
            DROP COLUMN generation,
            DROP COLUMN method,
            DROP COLUMN word_count,
            DROP COLUMN version_number,
            ADD CONSTRAINT uq_cover_letters_job_profile UNIQUE (job_id, profile_id)
        """
    )
    op.execute("DROP INDEX ix_resume_versions_base_version_id")
    op.execute(
        """
        ALTER TABLE resume_versions
            DROP CONSTRAINT ck_resume_versions_base_only_tailored,
            DROP CONSTRAINT ck_resume_versions_tailoring_json,
            DROP CONSTRAINT ck_resume_versions_changes_json,
            DROP CONSTRAINT fk_resume_versions_base_version_id,
            DROP COLUMN tailoring,
            DROP COLUMN changes,
            DROP COLUMN base_version_id
        """
    )
