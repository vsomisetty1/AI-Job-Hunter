-- =====================================================================
-- 0002: resume intelligence (Phase 4). FROZEN once applied.
--   * resume_versions: original / parsed / tailored versions; job is
--     optional (only tailored versions target a job); version numbers are
--     unique per resume
--   * resumes: parse status, method, error, file size
--   * candidate_profiles: inference status + queryable skills
-- NOTE: no percent character (run through the raw driver).
-- =====================================================================

-- ---------------------------------------------------------------- resumes
ALTER TABLE resumes
    ADD COLUMN size_bytes   integer NOT NULL DEFAULT 0,
    ADD COLUMN parse_status text NOT NULL DEFAULT 'pending',
    ADD COLUMN parse_method text,
    ADD COLUMN parse_error  text,
    ADD CONSTRAINT ck_resumes_size CHECK (size_bytes >= 0),
    ADD CONSTRAINT ck_resumes_parse_status
        CHECK (parse_status IN ('pending', 'parsed', 'failed')),
    ADD CONSTRAINT ck_resumes_parse_method
        CHECK (parse_method IS NULL OR parse_method IN ('deterministic', 'llm_assisted')),
    ADD CONSTRAINT ck_resumes_parsed_has_time
        CHECK (parse_status <> 'parsed' OR parsed_at IS NOT NULL);

-- -------------------------------------------------------- resume_versions
ALTER TABLE resume_versions
    ADD COLUMN kind           text NOT NULL DEFAULT 'tailored',
    ADD COLUMN source         text NOT NULL DEFAULT 'tailoring',
    ADD COLUMN target_role    text,
    ADD COLUMN target_company text,
    ALTER COLUMN job_id DROP NOT NULL;

-- Version numbers become unique per resume (across jobs and kinds).
ALTER TABLE resume_versions DROP CONSTRAINT uq_resume_versions_resume_job_version;
UPDATE resume_versions rv
SET version_number = n.rn
FROM (
    SELECT id, row_number() OVER (PARTITION BY resume_id ORDER BY created_at, id) AS rn
    FROM resume_versions
) n
WHERE rv.id = n.id AND rv.version_number <> n.rn;

ALTER TABLE resume_versions
    ADD CONSTRAINT uq_resume_versions_resume_version UNIQUE (resume_id, version_number),
    ADD CONSTRAINT ck_resume_versions_kind CHECK (kind IN ('original', 'parsed', 'tailored')),
    ADD CONSTRAINT ck_resume_versions_source
        CHECK (source IN ('upload', 'parser', 'user_edit', 'tailoring')),
    -- Only tailored versions target a job / role / company ...
    ADD CONSTRAINT ck_resume_versions_untailored_no_target
        CHECK (kind = 'tailored'
               OR (job_id IS NULL AND target_role IS NULL AND target_company IS NULL)),
    -- ... and a tailored version must target something.
    ADD CONSTRAINT ck_resume_versions_tailored_has_target
        CHECK (kind <> 'tailored' OR job_id IS NOT NULL OR target_role IS NOT NULL),
    ADD CONSTRAINT ck_resume_versions_target_role
        CHECK (target_role IS NULL OR btrim(target_role) <> ''),
    ADD CONSTRAINT ck_resume_versions_target_company
        CHECK (target_company IS NULL OR btrim(target_company) <> '');

CREATE INDEX ix_resume_versions_resume_kind
    ON resume_versions (resume_id, kind, version_number DESC);

-- ------------------------------------------------------ candidate_profiles
ALTER TABLE candidate_profiles
    ADD COLUMN skills           text[] NOT NULL DEFAULT '{}',
    ADD COLUMN inference_status text NOT NULL DEFAULT 'none',
    ADD COLUMN inference_error  text,
    ADD COLUMN inferred_at      timestamptz,
    ADD CONSTRAINT ck_candidate_profiles_inference_status
        CHECK (inference_status IN ('none', 'pending', 'running', 'complete', 'failed'));
