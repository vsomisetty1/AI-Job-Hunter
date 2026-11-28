-- =====================================================================
-- 0007: learning and insights (Phase 9). FROZEN once applied.
--   * interview_events: what happened after applying, entered by the user:
--     recruiter response, recruiter/phone screens, technical, hiring manager,
--     onsite and final rounds, offer, rejection, withdrawal; each with a
--     status (scheduled/completed/cancelled/no_show), date and notes.
--   * applications: 'withdrawn' status and outcome milestones
--     (responded_at, first_interview_at, offer_at, rejected_at,
--     withdrawn_at), derived from interview_events by the app.
--   * application_events: outcome event types and the withdrawn status.
--   * companies.industry: set by the user (never inferred), for analytics.
--   * learning_snapshots: the Learning Agent's computed metrics, insights
--     and recommendations over time (append-only).
--   * recommendation_states: recommendations the user dismissed or did.
-- NOTE: no percent character (run through the raw driver).
-- =====================================================================

-- --------------------------------------------------------- applications
ALTER TABLE applications
    DROP CONSTRAINT ck_applications_status,
    ADD CONSTRAINT ck_applications_status
        CHECK (status IN ('drafted', 'ready', 'submitted', 'interview', 'rejected', 'offer',
                          'withdrawn')),
    ADD COLUMN responded_at       timestamptz,
    ADD COLUMN first_interview_at timestamptz,
    ADD COLUMN offer_at           timestamptz,
    ADD COLUMN rejected_at        timestamptz,
    ADD COLUMN withdrawn_at       timestamptz,
    -- Outcomes exist only for applications that were sent.
    ADD CONSTRAINT ck_applications_outcomes_after_submit
        CHECK (submitted_at IS NOT NULL OR (responded_at IS NULL AND first_interview_at IS NULL
               AND offer_at IS NULL AND rejected_at IS NULL AND withdrawn_at IS NULL));

-- --------------------------------------------------- application_events
ALTER TABLE application_events
    DROP CONSTRAINT ck_application_events_type,
    ADD CONSTRAINT ck_application_events_type
        CHECK (event_type IN ('created', 'status_changed', 'approved', 'automation_started',
                              'checkpoint', 'retry', 'needs_manual', 'failed', 'submitted', 'note',
                              'outcome_recorded', 'outcome_updated', 'outcome_removed')),
    DROP CONSTRAINT ck_application_events_from_status,
    ADD CONSTRAINT ck_application_events_from_status
        CHECK (from_status IS NULL OR from_status IN
               ('drafted', 'ready', 'submitted', 'interview', 'rejected', 'offer', 'withdrawn')),
    DROP CONSTRAINT ck_application_events_to_status,
    ADD CONSTRAINT ck_application_events_to_status
        CHECK (to_status IS NULL OR to_status IN
               ('drafted', 'ready', 'submitted', 'interview', 'rejected', 'offer', 'withdrawn'));

-- ----------------------------------------------------- interview_events
CREATE TABLE interview_events (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    application_id uuid NOT NULL,
    stage          text NOT NULL,
    status         text NOT NULL DEFAULT 'completed',
    occurred_at    timestamptz NOT NULL,
    notes          text,
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fk_interview_events_application_id
        FOREIGN KEY (application_id) REFERENCES applications(id) ON DELETE CASCADE,
    CONSTRAINT ck_interview_events_stage
        CHECK (stage IN ('recruiter_response', 'recruiter_screen', 'phone_screen',
                         'technical_interview', 'hiring_manager_interview', 'onsite',
                         'final_round', 'offer', 'rejection', 'withdrawal')),
    CONSTRAINT ck_interview_events_status
        CHECK (status IN ('scheduled', 'completed', 'cancelled', 'no_show')),
    -- A response, an offer, a rejection or a withdrawal has happened or it has not.
    CONSTRAINT ck_interview_events_terminal_completed
        CHECK (stage NOT IN ('recruiter_response', 'offer', 'rejection', 'withdrawal')
               OR status = 'completed'),
    CONSTRAINT ck_interview_events_notes CHECK (notes IS NULL OR length(notes) <= 4000)
);
CREATE INDEX ix_interview_events_application_id ON interview_events (application_id, occurred_at);
CREATE INDEX ix_interview_events_stage ON interview_events (stage, occurred_at);
CREATE TRIGGER trg_interview_events_updated
    BEFORE UPDATE ON interview_events
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ------------------------------------------------------------ companies
ALTER TABLE companies
    ADD COLUMN industry text,
    ADD CONSTRAINT ck_companies_industry
        CHECK (industry IS NULL OR (btrim(industry) <> '' AND length(industry) <= 80));

-- --------------------------------------------------- learning_snapshots
CREATE TABLE learning_snapshots (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    -- sha256 of the inputs: an unchanged history is not stored twice in a row
    data_hash       text NOT NULL,
    summary         jsonb NOT NULL DEFAULT '{}'::jsonb,
    insights        jsonb NOT NULL DEFAULT '[]'::jsonb,
    recommendations jsonb NOT NULL DEFAULT '[]'::jsonb,
    created_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_learning_snapshots_hash CHECK (data_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_learning_snapshots_summary_json CHECK (jsonb_typeof(summary) = 'object'),
    CONSTRAINT ck_learning_snapshots_insights_json CHECK (jsonb_typeof(insights) = 'array'),
    CONSTRAINT ck_learning_snapshots_recommendations_json
        CHECK (jsonb_typeof(recommendations) = 'array')
);
CREATE INDEX ix_learning_snapshots_created_at ON learning_snapshots (created_at);

-- ------------------------------------------------ recommendation_states
CREATE TABLE recommendation_states (
    key        text PRIMARY KEY,
    status     text NOT NULL,
    note       text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_recommendation_states_key CHECK (key ~ '^[a-z0-9_:.-]{1,200}$'),
    CONSTRAINT ck_recommendation_states_status CHECK (status IN ('dismissed', 'done'))
);
CREATE TRIGGER trg_recommendation_states_updated
    BEFORE UPDATE ON recommendation_states
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
