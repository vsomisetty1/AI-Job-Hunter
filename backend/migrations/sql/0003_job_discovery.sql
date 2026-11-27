-- =====================================================================
-- 0003: job discovery (Phase 5). FROZEN once applied.
--   * jobs.content_hash: hash of the normalized posting, so a refresh can
--     tell "updated" from "unchanged" without comparing every column
--   * jobs.expired_at: when the posting disappeared from its board
--   * discovery_runs: one row per crawl (monitoring); at most one running
-- NOTE: no percent character (run through the raw driver).
-- =====================================================================

ALTER TABLE jobs
    ADD COLUMN content_hash text,
    ADD COLUMN expired_at   timestamptz,
    ADD CONSTRAINT ck_jobs_content_hash
        CHECK (content_hash IS NULL OR content_hash ~ '^[0-9a-f]{64}$'),
    ADD CONSTRAINT ck_jobs_expired_at
        CHECK (expired_at IS NULL OR status = 'expired');

CREATE TABLE discovery_runs (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    trigger             text NOT NULL,
    status              text NOT NULL DEFAULT 'running',
    companies_total     integer NOT NULL DEFAULT 0,
    companies_succeeded integer NOT NULL DEFAULT 0,
    companies_failed    integer NOT NULL DEFAULT 0,
    jobs_found          integer NOT NULL DEFAULT 0,
    jobs_inserted       integer NOT NULL DEFAULT 0,
    jobs_updated        integer NOT NULL DEFAULT 0,
    jobs_unchanged      integer NOT NULL DEFAULT 0,
    jobs_skipped        integer NOT NULL DEFAULT 0,
    jobs_expired        integer NOT NULL DEFAULT 0,
    error               text,
    -- Per-company results: [{company_id, source, slug, status, counts, error}]
    details             jsonb NOT NULL DEFAULT '[]'::jsonb,
    started_at          timestamptz NOT NULL DEFAULT now(),
    finished_at         timestamptz,
    duration_ms         integer,
    updated_at          timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_discovery_runs_trigger CHECK (trigger IN ('manual', 'scheduled')),
    CONSTRAINT ck_discovery_runs_status
        CHECK (status IN ('running', 'succeeded', 'partial', 'failed', 'cancelled')),
    CONSTRAINT ck_discovery_runs_counts CHECK (
        companies_total >= 0 AND companies_succeeded >= 0 AND companies_failed >= 0
        AND jobs_found >= 0 AND jobs_inserted >= 0 AND jobs_updated >= 0
        AND jobs_unchanged >= 0 AND jobs_skipped >= 0 AND jobs_expired >= 0),
    CONSTRAINT ck_discovery_runs_finished
        CHECK (finished_at IS NULL OR finished_at >= started_at),
    CONSTRAINT ck_discovery_runs_done_has_finish
        CHECK (status = 'running' OR finished_at IS NOT NULL),
    CONSTRAINT ck_discovery_runs_duration CHECK (duration_ms IS NULL OR duration_ms >= 0),
    CONSTRAINT ck_discovery_runs_details_json CHECK (jsonb_typeof(details) = 'array')
);
CREATE INDEX ix_discovery_runs_started_at ON discovery_runs (started_at DESC);
-- One crawl at a time (a second "run now" while one is running is refused).
CREATE UNIQUE INDEX uq_discovery_runs_one_running ON discovery_runs ((true))
    WHERE status = 'running';
CREATE TRIGGER trg_discovery_runs_updated
    BEFORE UPDATE ON discovery_runs
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
