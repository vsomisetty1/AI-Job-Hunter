-- =====================================================================
-- 0008: approval mode only (Phase 10, ADR-016). FROZEN once applied.
--   Autonomous mode was never built: no code path submits without the
--   user's confirmation, and application_submissions.mode already allows
--   only APPROVAL_MODE (0006). The settings row and applications could
--   still store AUTONOMOUS_MODE, which claimed a capability the app does
--   not have. Pin both to APPROVAL_MODE until a future ADR enables it.
--   settings.auto_apply_threshold and daily_application_cap are kept,
--   unused, for that future decision (the API no longer accepts them).
-- NOTE: no percent character (run through the raw driver).
-- =====================================================================

UPDATE settings SET application_mode = 'APPROVAL_MODE'
    WHERE application_mode <> 'APPROVAL_MODE';
UPDATE applications SET application_mode = 'APPROVAL_MODE'
    WHERE application_mode <> 'APPROVAL_MODE';

ALTER TABLE settings
    DROP CONSTRAINT ck_settings_mode,
    ADD CONSTRAINT ck_settings_mode CHECK (application_mode IN ('APPROVAL_MODE'));

ALTER TABLE applications
    DROP CONSTRAINT ck_applications_mode,
    ADD CONSTRAINT ck_applications_mode CHECK (application_mode IN ('APPROVAL_MODE'));
