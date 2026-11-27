-- =====================================================================
-- 0005: application packages (Phase 7). FROZEN once applied.
--   * application_packages: tailored resume + cover letter + answers for
--     one job, with the review/approval lifecycle. Versioned per job and
--     profile; at most one live package (older ones are superseded).
--   * resume_versions: the version a tailored resume was built from, every
--     change with its reason (section, before/after, timestamp), and the
--     tailoring notes (matched/missing skills, method)
--   * cover_letters: versioned (one row per generation), word count and
--     how it was written
--   * application_answers: answers belong to a package (before an
--     application exists) or an application; the evidence behind each
--     answer is stored; 'rules' source for deterministic answers
--   * settings: willingness to relocate, for relocation questions
-- NOTE: no percent character (run through the raw driver).
-- =====================================================================

-- ------------------------------------------------------- resume_versions
ALTER TABLE resume_versions
    -- The parsed version a tailored version was built from (for the diff).
    ADD COLUMN base_version_id uuid,
    -- [{"section", "item", "field", "before", "after", "reason", "at"}]
    ADD COLUMN changes         jsonb NOT NULL DEFAULT '[]'::jsonb,
    -- {"method", "matched_skills", "missing_skills", "notes", "model", ...}
    ADD COLUMN tailoring       jsonb NOT NULL DEFAULT '{}'::jsonb,
    ADD CONSTRAINT fk_resume_versions_base_version_id
        FOREIGN KEY (base_version_id) REFERENCES resume_versions(id) ON DELETE SET NULL,
    ADD CONSTRAINT ck_resume_versions_changes_json CHECK (jsonb_typeof(changes) = 'array'),
    ADD CONSTRAINT ck_resume_versions_tailoring_json CHECK (jsonb_typeof(tailoring) = 'object'),
    ADD CONSTRAINT ck_resume_versions_base_only_tailored
        CHECK (base_version_id IS NULL OR kind = 'tailored');
CREATE INDEX ix_resume_versions_base_version_id
    ON resume_versions (base_version_id) WHERE base_version_id IS NOT NULL;

-- --------------------------------------------------------- cover_letters
ALTER TABLE cover_letters
    ADD COLUMN version_number integer NOT NULL DEFAULT 1,
    ADD COLUMN word_count     integer NOT NULL DEFAULT 0,
    -- rules: composed from profile/resume facts; claude: written by Claude
    -- and checked against those facts
    ADD COLUMN method         text NOT NULL DEFAULT 'rules',
    -- {"facts": [...], "notes": [...], "prompt_version", ...}
    ADD COLUMN generation     jsonb NOT NULL DEFAULT '{}'::jsonb,
    DROP CONSTRAINT uq_cover_letters_job_profile,
    ADD CONSTRAINT ck_cover_letters_version CHECK (version_number >= 1),
    ADD CONSTRAINT ck_cover_letters_word_count CHECK (word_count >= 0),
    ADD CONSTRAINT ck_cover_letters_method CHECK (method IN ('rules', 'claude')),
    ADD CONSTRAINT ck_cover_letters_generation_json CHECK (jsonb_typeof(generation) = 'object'),
    ADD CONSTRAINT uq_cover_letters_job_profile_version
        UNIQUE (job_id, profile_id, version_number);

-- --------------------------------------------------- application_packages
CREATE TABLE application_packages (
    id                     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id                 uuid NOT NULL,
    profile_id             uuid NOT NULL,
    version_number         integer NOT NULL DEFAULT 1,
    -- generating -> generated -> reviewed -> approved -> submitted;
    -- rejected, failed and superseded end a package.
    status                 text NOT NULL DEFAULT 'generating',
    job_score_id           uuid,
    base_resume_version_id uuid,
    resume_version_id      uuid,
    cover_letter_id        uuid,
    -- Set on approval: the application row automation will work from.
    application_id         uuid,
    -- The score as it was when the package was generated (scores change).
    score_snapshot         jsonb NOT NULL DEFAULT '{}'::jsonb,
    -- {"use_llm", "llm_used", "warnings", "steps", "usage"}
    generation             jsonb NOT NULL DEFAULT '{}'::jsonb,
    error                  text,
    review_notes           text,
    rejection_reason       text,
    generated_at           timestamptz,
    reviewed_at            timestamptz,
    approved_at            timestamptz,
    rejected_at            timestamptz,
    submitted_at           timestamptz,
    created_at             timestamptz NOT NULL DEFAULT now(),
    updated_at             timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fk_application_packages_job_id
        FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE,
    CONSTRAINT fk_application_packages_profile_id
        FOREIGN KEY (profile_id) REFERENCES candidate_profiles(id) ON DELETE CASCADE,
    -- Composite FKs: every artifact belongs to the package's job.
    CONSTRAINT fk_application_packages_job_score_id
        FOREIGN KEY (job_score_id, job_id)
        REFERENCES job_scores(id, job_id) ON DELETE SET NULL (job_score_id),
    CONSTRAINT fk_application_packages_resume_version_id
        FOREIGN KEY (resume_version_id, job_id)
        REFERENCES resume_versions(id, job_id) ON DELETE SET NULL (resume_version_id),
    CONSTRAINT fk_application_packages_cover_letter_id
        FOREIGN KEY (cover_letter_id, job_id)
        REFERENCES cover_letters(id, job_id) ON DELETE SET NULL (cover_letter_id),
    CONSTRAINT fk_application_packages_base_resume_version_id
        FOREIGN KEY (base_resume_version_id) REFERENCES resume_versions(id) ON DELETE SET NULL,
    CONSTRAINT fk_application_packages_application_id
        FOREIGN KEY (application_id) REFERENCES applications(id) ON DELETE SET NULL,
    CONSTRAINT ck_application_packages_status CHECK (status IN (
        'generating', 'generated', 'reviewed', 'approved', 'rejected', 'submitted', 'failed',
        'superseded')),
    CONSTRAINT ck_application_packages_version CHECK (version_number >= 1),
    CONSTRAINT ck_application_packages_score_json CHECK (jsonb_typeof(score_snapshot) = 'object'),
    CONSTRAINT ck_application_packages_generation_json
        CHECK (jsonb_typeof(generation) = 'object'),
    -- Lifecycle timestamps follow the status.
    CONSTRAINT ck_application_packages_generated
        CHECK (status IN ('generating', 'failed') OR generated_at IS NOT NULL),
    CONSTRAINT ck_application_packages_approved
        CHECK (status NOT IN ('approved', 'submitted') OR approved_at IS NOT NULL),
    CONSTRAINT ck_application_packages_rejected
        CHECK (status <> 'rejected' OR rejected_at IS NOT NULL),
    CONSTRAINT ck_application_packages_submitted
        CHECK (status <> 'submitted' OR submitted_at IS NOT NULL),
    CONSTRAINT ck_application_packages_failed CHECK (status <> 'failed' OR error IS NOT NULL),
    CONSTRAINT uq_application_packages_job_profile_version
        UNIQUE (job_id, profile_id, version_number)
);
-- One live package per job and profile; regenerating supersedes the old one.
CREATE UNIQUE INDEX uq_application_packages_live
    ON application_packages (job_id, profile_id)
    WHERE status IN ('generating', 'generated', 'reviewed', 'approved', 'submitted');
-- The approval queue.
CREATE INDEX ix_application_packages_status_created
    ON application_packages (status, created_at DESC);
CREATE INDEX ix_application_packages_profile_id ON application_packages (profile_id);
CREATE INDEX ix_application_packages_job_score_id
    ON application_packages (job_score_id) WHERE job_score_id IS NOT NULL;
CREATE INDEX ix_application_packages_resume_version_id
    ON application_packages (resume_version_id) WHERE resume_version_id IS NOT NULL;
CREATE INDEX ix_application_packages_base_resume_version_id
    ON application_packages (base_resume_version_id) WHERE base_resume_version_id IS NOT NULL;
CREATE INDEX ix_application_packages_cover_letter_id
    ON application_packages (cover_letter_id) WHERE cover_letter_id IS NOT NULL;
CREATE INDEX ix_application_packages_application_id
    ON application_packages (application_id) WHERE application_id IS NOT NULL;
CREATE TRIGGER trg_application_packages_updated
    BEFORE UPDATE ON application_packages
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- --------------------------------------------------- application_answers
ALTER TABLE application_answers
    ALTER COLUMN application_id DROP NOT NULL,
    ADD COLUMN package_id uuid,
    -- Facts the answer was built from: [{"source", "fact"}]
    ADD COLUMN evidence   jsonb NOT NULL DEFAULT '[]'::jsonb,
    ADD CONSTRAINT fk_application_answers_package_id
        FOREIGN KEY (package_id) REFERENCES application_packages(id) ON DELETE CASCADE,
    ADD CONSTRAINT ck_application_answers_one_owner
        CHECK (num_nonnulls(application_id, package_id) = 1),
    ADD CONSTRAINT ck_application_answers_evidence_json CHECK (jsonb_typeof(evidence) = 'array'),
    ADD CONSTRAINT ck_application_answers_answer CHECK (btrim(answer) <> ''),
    DROP CONSTRAINT ck_application_answers_source,
    ADD CONSTRAINT ck_application_answers_source
        CHECK (source IN ('profile', 'settings', 'rules', 'llm', 'user')),
    ADD CONSTRAINT uq_application_answers_package_question UNIQUE (package_id, question_hash);

-- --------------------------------------------------------------- settings
ALTER TABLE settings
    -- NULL: not stated (relocation answers are then flagged for review).
    ADD COLUMN willing_to_relocate boolean;
