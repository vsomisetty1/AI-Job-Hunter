-- =====================================================================
-- 0004: filtering and scoring (Phase 6). FROZEN once applied.
--   * jobs: the rule-filter decision (filter_result, filter_hash,
--     filtered_at) and cross-board duplicate links (duplicate_of)
--   * job_scores: rule-based scores next to Claude scores. One current row
--     per job + profile + scoring_method, updated in place (updated_at);
--     Claude-only fields become optional; per-component scores and a
--     breakdown explain every number; input_hash lets a rerun skip jobs
--     whose inputs did not change
--   * settings: opt-in Claude scoring and its minimum rule score
-- NOTE: no percent character (run through the raw driver).
-- =====================================================================

-- ------------------------------------------------------------------ jobs
ALTER TABLE jobs
    -- Set when the same posting (company + title + location) is already
    -- stored from another board; the earliest one is kept.
    ADD COLUMN duplicate_of  uuid,
    -- {"passed": bool, "version": str, "checks": [{"rule", "passed", "reason"}]}
    ADD COLUMN filter_result jsonb,
    -- Hash of the rule version, the preferences and the job fields the rules
    -- read: an unchanged hash means the stored decision is still current.
    ADD COLUMN filter_hash   text,
    ADD COLUMN filtered_at   timestamptz,
    ADD CONSTRAINT fk_jobs_duplicate_of
        FOREIGN KEY (duplicate_of) REFERENCES jobs(id) ON DELETE SET NULL,
    ADD CONSTRAINT ck_jobs_not_own_duplicate CHECK (duplicate_of IS NULL OR duplicate_of <> id),
    ADD CONSTRAINT ck_jobs_filter_result_json
        CHECK (filter_result IS NULL OR jsonb_typeof(filter_result) = 'object'),
    ADD CONSTRAINT ck_jobs_filter_hash
        CHECK (filter_hash IS NULL OR filter_hash ~ '^[0-9a-f]{64}$'),
    ADD CONSTRAINT ck_jobs_filtered_consistent
        CHECK ((filter_result IS NULL) = (filtered_at IS NULL)
               AND (filter_hash IS NULL) = (filtered_at IS NULL));
CREATE INDEX ix_jobs_duplicate_of ON jobs (duplicate_of) WHERE duplicate_of IS NOT NULL;

-- ------------------------------------------------------------ job_scores
-- The table had no writer before this phase; keep only the newest row per
-- job + profile so the new uniqueness rule can be added on any database.
DELETE FROM job_scores a
    USING job_scores b
    WHERE a.job_id = b.job_id AND a.profile_id = b.profile_id
      AND (a.created_at, a.id) < (b.created_at, b.id);

ALTER TABLE job_scores
    ADD COLUMN scoring_method  text NOT NULL DEFAULT 'claude',
    ADD COLUMN skills_score    smallint,
    ADD COLUMN seniority_score smallint,
    ADD COLUMN location_score  smallint,
    ADD COLUMN relevance_score smallint,
    -- Per-component scores, weights and the evidence behind them.
    ADD COLUMN breakdown       jsonb NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN input_hash      text,
    ADD COLUMN updated_at      timestamptz NOT NULL DEFAULT now(),
    ALTER COLUMN interview_probability DROP NOT NULL,
    ALTER COLUMN salary_score DROP NOT NULL,
    ALTER COLUMN growth_score DROP NOT NULL,
    ALTER COLUMN company_score DROP NOT NULL,
    ALTER COLUMN model DROP NOT NULL,
    ALTER COLUMN prompt_version DROP NOT NULL,
    DROP CONSTRAINT uq_job_scores_job_profile_prompt;

-- Rows written before 0004 came from Claude (the default above); new rows
-- default to the rule-based scorer.
ALTER TABLE job_scores ALTER COLUMN scoring_method SET DEFAULT 'rules';

ALTER TABLE job_scores
    ADD CONSTRAINT ck_job_scores_method CHECK (scoring_method IN ('rules', 'claude')),
    ADD CONSTRAINT ck_job_scores_components CHECK (
        (skills_score IS NULL OR skills_score BETWEEN 0 AND 100)
        AND (seniority_score IS NULL OR seniority_score BETWEEN 0 AND 100)
        AND (location_score IS NULL OR location_score BETWEEN 0 AND 100)
        AND (relevance_score IS NULL OR relevance_score BETWEEN 0 AND 100)),
    -- Claude rows say which model and prompt produced them.
    ADD CONSTRAINT ck_job_scores_claude_fields
        CHECK (scoring_method <> 'claude' OR (model IS NOT NULL AND prompt_version IS NOT NULL)),
    -- Rule-based rows cost nothing.
    ADD CONSTRAINT ck_job_scores_rules_no_tokens
        CHECK (scoring_method <> 'rules' OR (input_tokens = 0 AND output_tokens = 0)),
    ADD CONSTRAINT ck_job_scores_breakdown_json CHECK (jsonb_typeof(breakdown) = 'object'),
    ADD CONSTRAINT ck_job_scores_input_hash
        CHECK (input_hash IS NULL OR input_hash ~ '^[0-9a-f]{64}$'),
    ADD CONSTRAINT uq_job_scores_job_profile_method UNIQUE (job_id, profile_id, scoring_method);

CREATE TRIGGER trg_job_scores_updated
    BEFORE UPDATE ON job_scores
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- -------------------------------------------------------------- settings
ALTER TABLE settings
    -- Claude scoring runs only when the owner opts in AND an API key is set.
    ADD COLUMN claude_scoring_enabled   boolean NOT NULL DEFAULT false,
    -- Only jobs whose rule-based score reaches this are sent to Claude.
    ADD COLUMN claude_scoring_min_score smallint NOT NULL DEFAULT 60,
    ADD CONSTRAINT ck_settings_claude_min_score CHECK (claude_scoring_min_score BETWEEN 0 AND 100);
