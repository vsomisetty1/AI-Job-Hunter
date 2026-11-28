"""Filtering and scoring: filter decisions and duplicate links on jobs, rule-based
scores in job_scores, opt-in Claude scoring settings.

Executes the FROZEN snapshot migrations/sql/0004_filtering_scoring.sql.

Downgrade deletes the score rows the old schema cannot hold (rule-based rows
and rows missing a Claude-only field) before restoring the NOT NULL columns.

Revision ID: 0004
Revises: 0003
"""

from pathlib import Path

from alembic import context, op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

SQL_FILE = Path(__file__).resolve().parents[1] / "sql" / "0004_filtering_scoring.sql"


def upgrade() -> None:
    if context.is_offline_mode():
        raise RuntimeError("Offline (--sql) mode is not supported; run against a database.")
    op.get_bind().exec_driver_sql(SQL_FILE.read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE settings
            DROP CONSTRAINT ck_settings_claude_min_score,
            DROP COLUMN claude_scoring_min_score,
            DROP COLUMN claude_scoring_enabled
        """
    )
    op.execute(
        """
        DELETE FROM job_scores
        WHERE scoring_method = 'rules'
           OR interview_probability IS NULL OR salary_score IS NULL
           OR growth_score IS NULL OR company_score IS NULL
        """
    )
    op.execute("DROP TRIGGER trg_job_scores_updated ON job_scores")
    op.execute(
        """
        ALTER TABLE job_scores
            DROP CONSTRAINT uq_job_scores_job_profile_method,
            DROP CONSTRAINT ck_job_scores_input_hash,
            DROP CONSTRAINT ck_job_scores_breakdown_json,
            DROP CONSTRAINT ck_job_scores_rules_no_tokens,
            DROP CONSTRAINT ck_job_scores_claude_fields,
            DROP CONSTRAINT ck_job_scores_components,
            DROP CONSTRAINT ck_job_scores_method,
            DROP COLUMN updated_at,
            DROP COLUMN input_hash,
            DROP COLUMN breakdown,
            DROP COLUMN relevance_score,
            DROP COLUMN location_score,
            DROP COLUMN seniority_score,
            DROP COLUMN skills_score,
            DROP COLUMN scoring_method,
            ALTER COLUMN interview_probability SET NOT NULL,
            ALTER COLUMN salary_score SET NOT NULL,
            ALTER COLUMN growth_score SET NOT NULL,
            ALTER COLUMN company_score SET NOT NULL,
            ALTER COLUMN model SET NOT NULL,
            ALTER COLUMN prompt_version SET NOT NULL,
            ADD CONSTRAINT uq_job_scores_job_profile_prompt
                UNIQUE (job_id, profile_id, prompt_version)
        """
    )
    op.execute("DROP INDEX ix_jobs_duplicate_of")
    op.execute(
        """
        ALTER TABLE jobs
            DROP CONSTRAINT ck_jobs_filtered_consistent,
            DROP CONSTRAINT ck_jobs_filter_hash,
            DROP CONSTRAINT ck_jobs_filter_result_json,
            DROP CONSTRAINT ck_jobs_not_own_duplicate,
            DROP CONSTRAINT fk_jobs_duplicate_of,
            DROP COLUMN filtered_at,
            DROP COLUMN filter_hash,
            DROP COLUMN filter_result,
            DROP COLUMN duplicate_of
        """
    )
