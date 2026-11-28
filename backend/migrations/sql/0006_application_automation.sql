-- =====================================================================
-- 0006: application automation, approval mode (Phase 8). FROZEN once applied.
--   * application_submissions: one browser run that fills an approved
--     package into a real ATS form and waits for the user. Status:
--     queued -> in_progress -> waiting_for_review -> submitting -> submitted,
--     ending in failed or cancelled. Holds the checkpoint used to resume,
--     the review report, the user's edits, screenshots and errors.
--   * automation_logs: structured, append-only log lines per submission.
-- Safety, enforced here and not only in code:
--   * mode is APPROVAL_MODE only (autonomous submission is not built);
--   * a submission can only be 'submitted' after the user confirmed it
--     (confirmed_at), and at most one run per application is active.
-- NOTE: no percent character (run through the raw driver).
-- =====================================================================

CREATE TABLE application_submissions (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    application_id     uuid NOT NULL,
    package_id         uuid,
    platform           text NOT NULL,
    apply_url          text NOT NULL,
    mode               text NOT NULL DEFAULT 'APPROVAL_MODE',
    status             text NOT NULL DEFAULT 'queued',
    -- Last checkpointed step: where a retry resumes from.
    step               text NOT NULL DEFAULT 'queued',
    -- {"fields": [...], "uploads": {...}, "url": ..., "plan_version": ...}
    checkpoint         jsonb NOT NULL DEFAULT '{}'::jsonb,
    -- {"resume", "cover_letter", "answers", "missing", "problems", ...}
    review             jsonb NOT NULL DEFAULT '{}'::jsonb,
    -- field key -> value typed by the user during review
    edits              jsonb NOT NULL DEFAULT '{}'::jsonb,
    -- [{"path", "step", "label", "at"}]
    screenshots        jsonb NOT NULL DEFAULT '[]'::jsonb,
    attempts           integer NOT NULL DEFAULT 0,
    error              text,
    error_kind         text,
    confirmation_text  text,
    confirmed_at       timestamptz,
    queued_at          timestamptz NOT NULL DEFAULT now(),
    started_at         timestamptz,
    review_ready_at    timestamptz,
    submitted_at       timestamptz,
    failed_at          timestamptz,
    cancelled_at       timestamptz,
    created_at         timestamptz NOT NULL DEFAULT now(),
    updated_at         timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fk_application_submissions_application_id
        FOREIGN KEY (application_id) REFERENCES applications(id) ON DELETE CASCADE,
    CONSTRAINT fk_application_submissions_package_id
        FOREIGN KEY (package_id) REFERENCES application_packages(id) ON DELETE SET NULL,
    CONSTRAINT ck_application_submissions_platform
        CHECK (platform IN ('greenhouse', 'lever', 'ashby')),
    CONSTRAINT ck_application_submissions_apply_url CHECK (apply_url ~ '^https?://'),
    CONSTRAINT ck_application_submissions_mode CHECK (mode IN ('APPROVAL_MODE')),
    CONSTRAINT ck_application_submissions_status
        CHECK (status IN ('queued', 'in_progress', 'waiting_for_review', 'submitting',
                          'submitted', 'failed', 'cancelled')),
    CONSTRAINT ck_application_submissions_step
        CHECK (step IN ('queued', 'opening', 'filling', 'uploading', 'validating', 'review',
                        'submitting', 'confirming', 'done')),
    CONSTRAINT ck_application_submissions_error_kind
        CHECK (error_kind IS NULL OR error_kind IN
               ('browser_crash', 'timeout', 'network', 'upload_failed', 'validation_failed',
                'ats_changed', 'captcha', 'job_closed', 'unconfirmed', 'interrupted',
                'internal')),
    CONSTRAINT ck_application_submissions_attempts CHECK (attempts >= 0),
    CONSTRAINT ck_application_submissions_checkpoint_json
        CHECK (jsonb_typeof(checkpoint) = 'object'),
    CONSTRAINT ck_application_submissions_review_json CHECK (jsonb_typeof(review) = 'object'),
    CONSTRAINT ck_application_submissions_edits_json CHECK (jsonb_typeof(edits) = 'object'),
    CONSTRAINT ck_application_submissions_screenshots_json
        CHECK (jsonb_typeof(screenshots) = 'array'),
    -- Approval mode: nothing is submitted without the user's confirmation.
    CONSTRAINT ck_application_submissions_confirmed
        CHECK (status NOT IN ('submitting', 'submitted') OR confirmed_at IS NOT NULL),
    CONSTRAINT ck_application_submissions_submitted_at
        CHECK (status <> 'submitted' OR submitted_at IS NOT NULL),
    CONSTRAINT ck_application_submissions_failed
        CHECK (status <> 'failed' OR (failed_at IS NOT NULL AND error IS NOT NULL))
);
CREATE UNIQUE INDEX uq_application_submissions_active
    ON application_submissions (application_id)
    WHERE status IN ('queued', 'in_progress', 'waiting_for_review', 'submitting');
CREATE INDEX ix_application_submissions_application_id
    ON application_submissions (application_id, created_at);
CREATE INDEX ix_application_submissions_package_id
    ON application_submissions (package_id) WHERE package_id IS NOT NULL;
CREATE INDEX ix_application_submissions_status
    ON application_submissions (status, updated_at);
CREATE TRIGGER trg_application_submissions_updated
    BEFORE UPDATE ON application_submissions
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE automation_logs (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    submission_id  uuid NOT NULL,
    level          text NOT NULL DEFAULT 'info',
    step           text,
    message        text NOT NULL,
    detail         jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at     timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fk_automation_logs_submission_id
        FOREIGN KEY (submission_id) REFERENCES application_submissions(id) ON DELETE CASCADE,
    CONSTRAINT ck_automation_logs_level CHECK (level IN ('debug', 'info', 'warning', 'error')),
    CONSTRAINT ck_automation_logs_message CHECK (btrim(message) <> ''),
    CONSTRAINT ck_automation_logs_detail_json CHECK (jsonb_typeof(detail) = 'object')
);
CREATE INDEX ix_automation_logs_submission_id ON automation_logs (submission_id, created_at);
CREATE INDEX ix_automation_logs_created_at ON automation_logs (created_at);
CREATE INDEX ix_automation_logs_level ON automation_logs (level, created_at)
    WHERE level IN ('warning', 'error');
