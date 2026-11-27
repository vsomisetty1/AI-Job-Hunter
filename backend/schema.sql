-- =====================================================================
-- AI Job Hunter - PostgreSQL schema (requires PostgreSQL 15+)
--
-- Reference copy of the schema at Alembic head (migrations 0001-0006).
-- Migrations execute frozen SQL files in migrations/sql/; an integration
-- test checks that this file and the migrated database have the same
-- catalog (columns, constraints, indexes, triggers).
-- The SQLAlchemy models in app/models mirror this file.
--
-- Conventions
--   * plural snake_case table names; uuid primary keys (gen_random_uuid)
--   * constraint/index prefixes: ck_ check, uq_ unique, fk_ foreign key
--     (fk_<table>_<first column>), ix_ index, trg_ trigger
--   * timestamptz everywhere; created_at on every table (agent_runs uses
--     started_at); updated_at + trigger on every mutable table
--   * enum-like columns are text + CHECK (cheap to evolve, unlike ENUMs)
--   * scores are integer percentages 0-100
--   * deleting a job is blocked while applications exist (history is kept)
--   * NOTE: do not use the percent character in this file (the migration
--     runs it through the raw driver).
-- =====================================================================

CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ---------------------------------------------------------------------
-- candidate_profiles: parsed resume data + inferred career profile
-- ---------------------------------------------------------------------
CREATE TABLE candidate_profiles (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    full_name        text NOT NULL,
    email            text,
    phone            text,
    location         text,
    linkedin_url     text,
    portfolio_url    text,
    -- Full CandidateProfile: experience, skills, education, projects,
    -- certifications, publications, achievements
    profile          jsonb NOT NULL DEFAULT '{}'::jsonb,
    -- Agent 1 narrative output only (trajectory, rationale). The queryable
    -- fields below are the single home for roles/industries/seniority.
    inference        jsonb NOT NULL DEFAULT '{}'::jsonb,
    seniority        text,
    experience_level text,
    years_experience numeric(4,1),
    primary_roles    text[] NOT NULL DEFAULT '{}',
    related_roles    text[] NOT NULL DEFAULT '{}',
    industries       text[] NOT NULL DEFAULT '{}',
    skills           text[] NOT NULL DEFAULT '{}',
    -- Profile generation (Agent 1) lifecycle
    inference_status text NOT NULL DEFAULT 'none',
    inference_error  text,
    inferred_at      timestamptz,
    is_active        boolean NOT NULL DEFAULT true,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_candidate_profiles_name CHECK (btrim(full_name) <> ''),
    CONSTRAINT ck_candidate_profiles_years
        CHECK (years_experience IS NULL OR (years_experience >= 0 AND years_experience <= 70)),
    CONSTRAINT ck_candidate_profiles_email
        CHECK (email IS NULL OR position('@' in email) > 1),
    CONSTRAINT ck_candidate_profiles_profile_json CHECK (jsonb_typeof(profile) = 'object'),
    CONSTRAINT ck_candidate_profiles_inference_json CHECK (jsonb_typeof(inference) = 'object'),
    CONSTRAINT ck_candidate_profiles_inference_status
        CHECK (inference_status IN ('none', 'pending', 'running', 'complete', 'failed'))
);
-- MVP is single-user: at most one active profile.
CREATE UNIQUE INDEX uq_candidate_profiles_single_active
    ON candidate_profiles ((true)) WHERE is_active;
CREATE TRIGGER trg_candidate_profiles_updated
    BEFORE UPDATE ON candidate_profiles
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------
-- resumes: uploaded original files
-- ---------------------------------------------------------------------
CREATE TABLE resumes (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    profile_id   uuid NOT NULL,
    filename     text NOT NULL,
    file_type    text NOT NULL,
    storage_path text NOT NULL,
    content_hash text NOT NULL,
    size_bytes   integer NOT NULL DEFAULT 0,
    raw_text     text,
    parse_status text NOT NULL DEFAULT 'pending',
    parse_method text,
    parse_error  text,
    parsed_at    timestamptz,
    is_primary   boolean NOT NULL DEFAULT false,
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fk_resumes_profile_id
        FOREIGN KEY (profile_id) REFERENCES candidate_profiles(id) ON DELETE CASCADE,
    CONSTRAINT ck_resumes_filename CHECK (btrim(filename) <> ''),
    CONSTRAINT ck_resumes_file_type CHECK (file_type IN ('pdf', 'docx')),
    CONSTRAINT ck_resumes_content_hash CHECK (content_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_resumes_size CHECK (size_bytes >= 0),
    CONSTRAINT ck_resumes_parse_status
        CHECK (parse_status IN ('pending', 'parsed', 'failed')),
    CONSTRAINT ck_resumes_parse_method
        CHECK (parse_method IS NULL OR parse_method IN ('deterministic', 'llm_assisted')),
    CONSTRAINT ck_resumes_parsed_has_time
        CHECK (parse_status <> 'parsed' OR parsed_at IS NOT NULL),
    CONSTRAINT uq_resumes_profile_hash UNIQUE (profile_id, content_hash),
    CONSTRAINT uq_resumes_storage_path UNIQUE (storage_path)
);
CREATE UNIQUE INDEX uq_resumes_one_primary
    ON resumes (profile_id) WHERE is_primary;
CREATE TRIGGER trg_resumes_updated
    BEFORE UPDATE ON resumes
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------
-- companies: one row per job board (source + slug); owns crawl state
-- ---------------------------------------------------------------------
CREATE TABLE companies (
    id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name                 text NOT NULL,
    source               text NOT NULL,
    slug                 text NOT NULL,
    careers_url          text,
    is_tracked           boolean NOT NULL DEFAULT true,
    last_crawled_at      timestamptz,
    last_crawl_status    text,
    last_error           text,
    consecutive_failures integer NOT NULL DEFAULT 0,
    created_at           timestamptz NOT NULL DEFAULT now(),
    updated_at           timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_companies_name CHECK (btrim(name) <> ''),
    CONSTRAINT ck_companies_slug CHECK (btrim(slug) <> ''),
    CONSTRAINT ck_companies_source CHECK (source ~ '^[a-z_]+$'),
    CONSTRAINT ck_companies_crawl_status
        CHECK (last_crawl_status IS NULL OR last_crawl_status IN ('ok', 'error', 'not_found')),
    CONSTRAINT ck_companies_failures CHECK (consecutive_failures >= 0),
    CONSTRAINT uq_companies_source_slug UNIQUE (source, slug)
);
-- Crawl scheduler: tracked companies, never-crawled first, then oldest crawl.
CREATE INDEX ix_companies_crawl_queue
    ON companies (last_crawled_at ASC NULLS FIRST) WHERE is_tracked;
CREATE INDEX ix_companies_name_lower ON companies (lower(name));
CREATE TRIGGER trg_companies_updated
    BEFORE UPDATE ON companies
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------
-- jobs: normalized postings from all connectors
-- (source/company come from the owning companies row)
-- ---------------------------------------------------------------------
CREATE TABLE jobs (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id        uuid NOT NULL,
    external_id       text NOT NULL,
    title             text NOT NULL,
    location          text,
    remote_type       text NOT NULL DEFAULT 'unknown',
    employment_type   text,
    salary_min        integer,
    salary_max        integer,
    salary_currency   text,
    compensation_text text,
    description       text NOT NULL DEFAULT '',
    requirements      jsonb NOT NULL DEFAULT '[]'::jsonb,
    url               text NOT NULL,
    apply_url         text,
    -- Hash of normalized company + title + location (cross-source dedup).
    -- Deliberately NOT unique: one company may post identical titles.
    dedup_key         text NOT NULL,
    -- Hash of the normalized posting: a refresh compares it to detect changes.
    content_hash      text,
    status            text NOT NULL DEFAULT 'new',
    filter_reason     text,
    -- Rule-filter decision: {"passed", "version", "checks": [{"rule", "passed", "reason"}]}
    filter_result     jsonb,
    -- Hash of rule version + preferences + the job fields the rules read.
    filter_hash       text,
    filtered_at       timestamptz,
    -- The same posting already stored from another board (earliest kept).
    duplicate_of      uuid,
    posted_at         timestamptz,
    first_seen_at     timestamptz NOT NULL DEFAULT now(),
    last_seen_at      timestamptz NOT NULL DEFAULT now(),
    -- Set when the posting disappears from its board (status 'expired').
    expired_at        timestamptz,
    -- Raw connector payload (debugging). Large; candidate for pruning.
    raw               jsonb,
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now(),
    -- RESTRICT: never lose jobs (and the applications hanging off them)
    -- by deleting a company row.
    CONSTRAINT fk_jobs_company_id
        FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE RESTRICT,
    CONSTRAINT fk_jobs_duplicate_of
        FOREIGN KEY (duplicate_of) REFERENCES jobs(id) ON DELETE SET NULL,
    CONSTRAINT ck_jobs_external_id CHECK (btrim(external_id) <> ''),
    CONSTRAINT ck_jobs_title CHECK (btrim(title) <> ''),
    CONSTRAINT ck_jobs_remote_type
        CHECK (remote_type IN ('remote', 'hybrid', 'onsite', 'unknown')),
    CONSTRAINT ck_jobs_status
        CHECK (status IN ('new', 'filtered', 'scored', 'shortlisted', 'skipped', 'applied', 'expired')),
    CONSTRAINT ck_jobs_url CHECK (url ~ '^https?://'),
    CONSTRAINT ck_jobs_apply_url CHECK (apply_url IS NULL OR apply_url ~ '^https?://'),
    CONSTRAINT ck_jobs_salary_range
        CHECK (salary_min IS NULL OR salary_max IS NULL OR salary_min <= salary_max),
    CONSTRAINT ck_jobs_salary_nonneg
        CHECK ((salary_min IS NULL OR salary_min >= 0) AND (salary_max IS NULL OR salary_max >= 0)),
    CONSTRAINT ck_jobs_currency CHECK (salary_currency IS NULL OR salary_currency ~ '^[A-Z]{3}$'),
    CONSTRAINT ck_jobs_dedup_key CHECK (dedup_key ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_jobs_content_hash
        CHECK (content_hash IS NULL OR content_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_jobs_expired_at CHECK (expired_at IS NULL OR status = 'expired'),
    CONSTRAINT ck_jobs_requirements_json CHECK (jsonb_typeof(requirements) = 'array'),
    CONSTRAINT ck_jobs_raw_json CHECK (raw IS NULL OR jsonb_typeof(raw) = 'object'),
    CONSTRAINT ck_jobs_seen_order CHECK (last_seen_at >= first_seen_at),
    CONSTRAINT ck_jobs_not_own_duplicate CHECK (duplicate_of IS NULL OR duplicate_of <> id),
    CONSTRAINT ck_jobs_filter_result_json
        CHECK (filter_result IS NULL OR jsonb_typeof(filter_result) = 'object'),
    CONSTRAINT ck_jobs_filter_hash
        CHECK (filter_hash IS NULL OR filter_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_jobs_filtered_consistent
        CHECK ((filter_result IS NULL) = (filtered_at IS NULL)
               AND (filter_hash IS NULL) = (filtered_at IS NULL)),
    CONSTRAINT uq_jobs_company_external UNIQUE (company_id, external_id),
    CONSTRAINT uq_jobs_url UNIQUE (url)
);
-- Pipeline stages pull "status = X, oldest first".
CREATE INDEX ix_jobs_status_first_seen ON jobs (status, first_seen_at);
CREATE INDEX ix_jobs_dedup_key ON jobs (dedup_key);
-- Expiry sweep: jobs of a company not seen in the latest crawl.
CREATE INDEX ix_jobs_company_last_seen ON jobs (company_id, last_seen_at);
CREATE INDEX ix_jobs_posted_at ON jobs (posted_at DESC NULLS LAST);
CREATE INDEX ix_jobs_duplicate_of ON jobs (duplicate_of) WHERE duplicate_of IS NOT NULL;
CREATE TRIGGER trg_jobs_updated
    BEFORE UPDATE ON jobs
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------
-- resume_versions: tailored resume per job
-- ---------------------------------------------------------------------
CREATE TABLE resume_versions (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    resume_id      uuid NOT NULL,
    -- original: the uploaded file; parsed: structured data (parser or user
    -- edit); tailored: rewritten for a target job / role / company
    kind           text NOT NULL DEFAULT 'tailored',
    source         text NOT NULL DEFAULT 'tailoring',
    job_id         uuid,
    target_role    text,
    target_company text,
    version_number integer NOT NULL DEFAULT 1,
    -- Structured resume content used by the PDF/DOCX generators
    content        jsonb NOT NULL DEFAULT '{}'::jsonb,
    pdf_path       text,
    docx_path      text,
    ats_keywords   text[] NOT NULL DEFAULT '{}',
    change_summary text,
    -- Tailored versions: the parsed version they were built from, every
    -- change with its reason, and the tailoring notes.
    base_version_id uuid,
    -- [{"section", "item", "field", "before", "after", "reason", "at"}]
    changes        jsonb NOT NULL DEFAULT '[]'::jsonb,
    -- {"method", "matched_skills", "missing_skills", "notes", "model", ...}
    tailoring      jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fk_resume_versions_base_version_id
        FOREIGN KEY (base_version_id) REFERENCES resume_versions(id) ON DELETE SET NULL,
    CONSTRAINT fk_resume_versions_resume_id
        FOREIGN KEY (resume_id) REFERENCES resumes(id) ON DELETE CASCADE,
    CONSTRAINT fk_resume_versions_job_id
        FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE,
    CONSTRAINT ck_resume_versions_version CHECK (version_number >= 1),
    CONSTRAINT ck_resume_versions_content_json CHECK (jsonb_typeof(content) = 'object'),
    CONSTRAINT ck_resume_versions_changes_json CHECK (jsonb_typeof(changes) = 'array'),
    CONSTRAINT ck_resume_versions_tailoring_json CHECK (jsonb_typeof(tailoring) = 'object'),
    CONSTRAINT ck_resume_versions_base_only_tailored
        CHECK (base_version_id IS NULL OR kind = 'tailored'),
    CONSTRAINT ck_resume_versions_kind CHECK (kind IN ('original', 'parsed', 'tailored')),
    CONSTRAINT ck_resume_versions_source
        CHECK (source IN ('upload', 'parser', 'user_edit', 'tailoring')),
    CONSTRAINT ck_resume_versions_untailored_no_target
        CHECK (kind = 'tailored'
               OR (job_id IS NULL AND target_role IS NULL AND target_company IS NULL)),
    CONSTRAINT ck_resume_versions_tailored_has_target
        CHECK (kind <> 'tailored' OR job_id IS NOT NULL OR target_role IS NOT NULL),
    CONSTRAINT ck_resume_versions_target_role
        CHECK (target_role IS NULL OR btrim(target_role) <> ''),
    CONSTRAINT ck_resume_versions_target_company
        CHECK (target_company IS NULL OR btrim(target_company) <> ''),
    CONSTRAINT uq_resume_versions_resume_version UNIQUE (resume_id, version_number),
    -- Target for the composite FK from applications (same-job guarantee).
    CONSTRAINT uq_resume_versions_id_job UNIQUE (id, job_id)
);
CREATE INDEX ix_resume_versions_job_id ON resume_versions (job_id);
CREATE INDEX ix_resume_versions_resume_kind
    ON resume_versions (resume_id, kind, version_number DESC);
CREATE INDEX ix_resume_versions_base_version_id
    ON resume_versions (base_version_id) WHERE base_version_id IS NOT NULL;
CREATE TRIGGER trg_resume_versions_updated
    BEFORE UPDATE ON resume_versions
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------
-- job_scores: one current score per job + profile + scoring method.
--   rules:  deterministic scorer (always available, no tokens)
--   claude: optional Claude scoring of a shortlist
-- All scores are integer percentages 0-100. Claude-only fields
-- (interview_probability, growth_score, company_score) are NULL for rules.
-- ---------------------------------------------------------------------
CREATE TABLE job_scores (
    id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id                uuid NOT NULL,
    profile_id            uuid NOT NULL,
    scoring_method        text NOT NULL DEFAULT 'rules',
    overall_score         smallint NOT NULL,
    skills_score          smallint,
    seniority_score       smallint,
    location_score        smallint,
    relevance_score       smallint,
    salary_score          smallint,
    interview_probability smallint,
    growth_score          smallint,
    company_score         smallint,
    rationale             text,
    matched_skills        jsonb NOT NULL DEFAULT '[]'::jsonb,
    missing_skills        jsonb NOT NULL DEFAULT '[]'::jsonb,
    -- Per-component scores, weights and the evidence behind them.
    breakdown             jsonb NOT NULL DEFAULT '{}'::jsonb,
    -- Hash of everything the score was computed from (skip unchanged reruns).
    input_hash            text,
    model                 text,
    prompt_version        text,
    input_tokens          integer NOT NULL DEFAULT 0,
    output_tokens         integer NOT NULL DEFAULT 0,
    created_at            timestamptz NOT NULL DEFAULT now(),
    updated_at            timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fk_job_scores_job_id
        FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE,
    CONSTRAINT fk_job_scores_profile_id
        FOREIGN KEY (profile_id) REFERENCES candidate_profiles(id) ON DELETE CASCADE,
    CONSTRAINT ck_job_scores_method CHECK (scoring_method IN ('rules', 'claude')),
    CONSTRAINT ck_job_scores_overall CHECK (overall_score BETWEEN 0 AND 100),
    CONSTRAINT ck_job_scores_interview CHECK (interview_probability BETWEEN 0 AND 100),
    CONSTRAINT ck_job_scores_salary CHECK (salary_score BETWEEN 0 AND 100),
    CONSTRAINT ck_job_scores_growth CHECK (growth_score BETWEEN 0 AND 100),
    CONSTRAINT ck_job_scores_company CHECK (company_score BETWEEN 0 AND 100),
    CONSTRAINT ck_job_scores_components CHECK (
        (skills_score IS NULL OR skills_score BETWEEN 0 AND 100)
        AND (seniority_score IS NULL OR seniority_score BETWEEN 0 AND 100)
        AND (location_score IS NULL OR location_score BETWEEN 0 AND 100)
        AND (relevance_score IS NULL OR relevance_score BETWEEN 0 AND 100)),
    CONSTRAINT ck_job_scores_claude_fields
        CHECK (scoring_method <> 'claude' OR (model IS NOT NULL AND prompt_version IS NOT NULL)),
    CONSTRAINT ck_job_scores_rules_no_tokens
        CHECK (scoring_method <> 'rules' OR (input_tokens = 0 AND output_tokens = 0)),
    CONSTRAINT ck_job_scores_tokens CHECK (input_tokens >= 0 AND output_tokens >= 0),
    CONSTRAINT ck_job_scores_skills_json
        CHECK (jsonb_typeof(matched_skills) = 'array' AND jsonb_typeof(missing_skills) = 'array'),
    CONSTRAINT ck_job_scores_breakdown_json CHECK (jsonb_typeof(breakdown) = 'object'),
    CONSTRAINT ck_job_scores_input_hash
        CHECK (input_hash IS NULL OR input_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT uq_job_scores_job_profile_method UNIQUE (job_id, profile_id, scoring_method),
    -- Target for the composite FK from applications (same-job guarantee).
    CONSTRAINT uq_job_scores_id_job UNIQUE (id, job_id)
);
CREATE INDEX ix_job_scores_profile_overall ON job_scores (profile_id, overall_score DESC);
CREATE TRIGGER trg_job_scores_updated
    BEFORE UPDATE ON job_scores
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------
-- cover_letters: every generated version is kept (version_number per job
-- and profile); method says how it was written
-- ---------------------------------------------------------------------
CREATE TABLE cover_letters (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id     uuid NOT NULL,
    profile_id uuid NOT NULL,
    content    text NOT NULL,
    pdf_path   text,
    docx_path  text,
    model      text,
    version_number integer NOT NULL DEFAULT 1,
    word_count integer NOT NULL DEFAULT 0,
    -- rules: composed from profile/resume facts; claude: written by Claude
    -- and checked against those facts
    method     text NOT NULL DEFAULT 'rules',
    -- {"facts": [...], "notes": [...], "prompt_version", ...}
    generation jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fk_cover_letters_job_id
        FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE,
    CONSTRAINT fk_cover_letters_profile_id
        FOREIGN KEY (profile_id) REFERENCES candidate_profiles(id) ON DELETE CASCADE,
    CONSTRAINT ck_cover_letters_content CHECK (btrim(content) <> ''),
    CONSTRAINT ck_cover_letters_version CHECK (version_number >= 1),
    CONSTRAINT ck_cover_letters_word_count CHECK (word_count >= 0),
    CONSTRAINT ck_cover_letters_method CHECK (method IN ('rules', 'claude')),
    CONSTRAINT ck_cover_letters_generation_json CHECK (jsonb_typeof(generation) = 'object'),
    CONSTRAINT uq_cover_letters_job_profile_version
        UNIQUE (job_id, profile_id, version_number),
    -- Target for the composite FK from applications (same-job guarantee).
    CONSTRAINT uq_cover_letters_id_job UNIQUE (id, job_id)
);
CREATE INDEX ix_cover_letters_profile_id ON cover_letters (profile_id);
CREATE TRIGGER trg_cover_letters_updated
    BEFORE UPDATE ON cover_letters
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------
-- applications: lifecycle tracking + automation state.
-- Composite FKs guarantee the attached resume version, cover letter and
-- score all belong to the same job as the application. ON DELETE SET NULL
-- with a column list (PostgreSQL 15+) nulls only the artifact column.
-- ---------------------------------------------------------------------
CREATE TABLE applications (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id              uuid NOT NULL,
    profile_id          uuid NOT NULL,
    resume_version_id   uuid,
    cover_letter_id     uuid,
    job_score_id        uuid,
    -- User-visible pipeline status
    status              text NOT NULL DEFAULT 'drafted',
    -- Automation progress (separate so status stays the six tracked stages)
    automation_state    text NOT NULL DEFAULT 'pending',
    application_mode    text NOT NULL DEFAULT 'APPROVAL_MODE',
    -- Failure recovery: last completed step, form progress, etc.
    checkpoint          jsonb NOT NULL DEFAULT '{}'::jsonb,
    attempts            integer NOT NULL DEFAULT 0,
    last_error          text,
    confirmation_ref    text,
    notes               text,
    approved_at         timestamptz,
    submitted_at        timestamptz,
    status_updated_at   timestamptz NOT NULL DEFAULT now(),
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now(),
    -- RESTRICT: application history must survive job cleanup.
    CONSTRAINT fk_applications_job_id
        FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE RESTRICT,
    CONSTRAINT fk_applications_profile_id
        FOREIGN KEY (profile_id) REFERENCES candidate_profiles(id) ON DELETE CASCADE,
    CONSTRAINT fk_applications_resume_version_id
        FOREIGN KEY (resume_version_id, job_id)
        REFERENCES resume_versions(id, job_id) ON DELETE SET NULL (resume_version_id),
    CONSTRAINT fk_applications_cover_letter_id
        FOREIGN KEY (cover_letter_id, job_id)
        REFERENCES cover_letters(id, job_id) ON DELETE SET NULL (cover_letter_id),
    CONSTRAINT fk_applications_job_score_id
        FOREIGN KEY (job_score_id, job_id)
        REFERENCES job_scores(id, job_id) ON DELETE SET NULL (job_score_id),
    CONSTRAINT ck_applications_status
        CHECK (status IN ('drafted', 'ready', 'submitted', 'interview', 'rejected', 'offer')),
    CONSTRAINT ck_applications_automation_state
        CHECK (automation_state IN ('pending', 'in_progress', 'needs_manual', 'failed', 'completed')),
    CONSTRAINT ck_applications_mode
        CHECK (application_mode IN ('APPROVAL_MODE', 'AUTONOMOUS_MODE')),
    CONSTRAINT ck_applications_attempts CHECK (attempts >= 0),
    CONSTRAINT ck_applications_checkpoint_json CHECK (jsonb_typeof(checkpoint) = 'object'),
    CONSTRAINT ck_applications_submitted_at
        CHECK (status IN ('drafted', 'ready') OR submitted_at IS NOT NULL),
    CONSTRAINT ck_applications_completed_submitted
        CHECK (automation_state <> 'completed' OR submitted_at IS NOT NULL),
    CONSTRAINT uq_applications_job_profile UNIQUE (job_id, profile_id)
);
CREATE INDEX ix_applications_status_updated ON applications (status, status_updated_at DESC);
-- Worker queue: only unfinished automation work.
CREATE INDEX ix_applications_open_work
    ON applications (automation_state, created_at) WHERE automation_state <> 'completed';
-- Daily-cap and learning queries.
CREATE INDEX ix_applications_submitted_at ON applications (submitted_at DESC NULLS LAST);
CREATE INDEX ix_applications_profile_id ON applications (profile_id);
CREATE INDEX ix_applications_resume_version_id
    ON applications (resume_version_id) WHERE resume_version_id IS NOT NULL;
CREATE INDEX ix_applications_cover_letter_id
    ON applications (cover_letter_id) WHERE cover_letter_id IS NOT NULL;
CREATE INDEX ix_applications_job_score_id
    ON applications (job_score_id) WHERE job_score_id IS NOT NULL;
CREATE TRIGGER trg_applications_updated
    BEFORE UPDATE ON applications
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------
-- application_packages: tailored resume + cover letter + answers for one
-- job, with the review/approval lifecycle. Versioned per job and profile;
-- at most one live package (regenerating supersedes the old one).
-- ---------------------------------------------------------------------
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

-- ---------------------------------------------------------------------
-- application_events: append-only audit trail (replaces a JSON history
-- column, which cannot be indexed, queried or safely appended to)
-- ---------------------------------------------------------------------
CREATE TABLE application_events (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    application_id uuid NOT NULL,
    event_type     text NOT NULL,
    from_status    text,
    to_status      text,
    actor          text NOT NULL DEFAULT 'system',
    detail         jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at     timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fk_application_events_application_id
        FOREIGN KEY (application_id) REFERENCES applications(id) ON DELETE CASCADE,
    CONSTRAINT ck_application_events_type
        CHECK (event_type IN ('created', 'status_changed', 'approved', 'automation_started',
                              'checkpoint', 'retry', 'needs_manual', 'failed', 'submitted', 'note')),
    CONSTRAINT ck_application_events_actor CHECK (actor IN ('system', 'user', 'agent')),
    CONSTRAINT ck_application_events_from_status
        CHECK (from_status IS NULL OR from_status IN
               ('drafted', 'ready', 'submitted', 'interview', 'rejected', 'offer')),
    CONSTRAINT ck_application_events_to_status
        CHECK (to_status IS NULL OR to_status IN
               ('drafted', 'ready', 'submitted', 'interview', 'rejected', 'offer')),
    CONSTRAINT ck_application_events_detail_json CHECK (jsonb_typeof(detail) = 'object')
);
CREATE INDEX ix_application_events_app_created
    ON application_events (application_id, created_at);

-- ---------------------------------------------------------------------
-- application_answers: generated/entered answers to form questions
-- ---------------------------------------------------------------------
CREATE TABLE application_answers (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    -- Owner: the application, or (before one exists) the package.
    application_id uuid,
    package_id     uuid,
    question       text NOT NULL,
    -- sha256 of the normalized question text
    question_hash  text NOT NULL,
    -- Canonical key when recognised, e.g. work_authorization
    question_key   text,
    answer         text NOT NULL,
    source         text NOT NULL,
    confidence     numeric(3,2),
    needs_review   boolean NOT NULL DEFAULT false,
    -- Facts the answer was built from: [{"source", "fact"}]
    evidence       jsonb NOT NULL DEFAULT '[]'::jsonb,
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fk_application_answers_application_id
        FOREIGN KEY (application_id) REFERENCES applications(id) ON DELETE CASCADE,
    CONSTRAINT fk_application_answers_package_id
        FOREIGN KEY (package_id) REFERENCES application_packages(id) ON DELETE CASCADE,
    CONSTRAINT ck_application_answers_one_owner
        CHECK (num_nonnulls(application_id, package_id) = 1),
    CONSTRAINT ck_application_answers_evidence_json CHECK (jsonb_typeof(evidence) = 'array'),
    CONSTRAINT ck_application_answers_answer CHECK (btrim(answer) <> ''),
    CONSTRAINT ck_application_answers_source
        CHECK (source IN ('profile', 'settings', 'rules', 'llm', 'user')),
    CONSTRAINT ck_application_answers_confidence
        CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    CONSTRAINT ck_application_answers_hash CHECK (question_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT uq_application_answers_app_question UNIQUE (application_id, question_hash),
    CONSTRAINT uq_application_answers_package_question UNIQUE (package_id, question_hash)
);
CREATE INDEX ix_application_answers_needs_review
    ON application_answers (application_id) WHERE needs_review;
CREATE TRIGGER trg_application_answers_updated
    BEFORE UPDATE ON application_answers
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------
-- agent_runs: audit log + token/cost accounting. Grows without bound:
-- prune on started_at (see ix_agent_runs_started_at).
-- ---------------------------------------------------------------------
CREATE TABLE agent_runs (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_name     text NOT NULL,
    status         text NOT NULL DEFAULT 'running',
    job_id         uuid,
    application_id uuid,
    input_summary  jsonb NOT NULL DEFAULT '{}'::jsonb,
    output_summary jsonb NOT NULL DEFAULT '{}'::jsonb,
    error          text,
    input_tokens   integer NOT NULL DEFAULT 0,
    output_tokens  integer NOT NULL DEFAULT 0,
    cost_usd       numeric(10,6) NOT NULL DEFAULT 0,
    started_at     timestamptz NOT NULL DEFAULT now(),
    finished_at    timestamptz,
    duration_ms    integer,
    CONSTRAINT fk_agent_runs_job_id
        FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE SET NULL,
    CONSTRAINT fk_agent_runs_application_id
        FOREIGN KEY (application_id) REFERENCES applications(id) ON DELETE SET NULL,
    CONSTRAINT ck_agent_runs_name CHECK (btrim(agent_name) <> ''),
    CONSTRAINT ck_agent_runs_status
        CHECK (status IN ('running', 'succeeded', 'failed', 'cancelled')),
    CONSTRAINT ck_agent_runs_tokens CHECK (input_tokens >= 0 AND output_tokens >= 0),
    CONSTRAINT ck_agent_runs_cost CHECK (cost_usd >= 0),
    CONSTRAINT ck_agent_runs_duration CHECK (duration_ms IS NULL OR duration_ms >= 0),
    CONSTRAINT ck_agent_runs_finished
        CHECK (finished_at IS NULL OR finished_at >= started_at),
    CONSTRAINT ck_agent_runs_done_has_finish
        CHECK (status = 'running' OR finished_at IS NOT NULL),
    CONSTRAINT ck_agent_runs_summaries_json
        CHECK (jsonb_typeof(input_summary) = 'object' AND jsonb_typeof(output_summary) = 'object')
);
CREATE INDEX ix_agent_runs_agent_started ON agent_runs (agent_name, started_at DESC);
CREATE INDEX ix_agent_runs_started_at ON agent_runs (started_at);
CREATE INDEX ix_agent_runs_status ON agent_runs (status);
CREATE INDEX ix_agent_runs_job_id ON agent_runs (job_id) WHERE job_id IS NOT NULL;
CREATE INDEX ix_agent_runs_application_id
    ON agent_runs (application_id) WHERE application_id IS NOT NULL;

-- ---------------------------------------------------------------------
-- settings: single-row user preferences (tracked companies live in the
-- companies table)
-- ---------------------------------------------------------------------
CREATE TABLE settings (
    id                    smallint PRIMARY KEY DEFAULT 1,
    preferred_locations   text[] NOT NULL DEFAULT '{}',
    remote_preference     text NOT NULL DEFAULT 'any',
    job_types             text[] NOT NULL DEFAULT '{}',
    salary_min            integer,
    salary_target         integer,
    salary_currency       text NOT NULL DEFAULT 'USD',
    work_authorization    text,
    visa_status           text,
    requires_sponsorship  boolean NOT NULL DEFAULT false,
    excluded_companies    text[] NOT NULL DEFAULT '{}',
    excluded_keywords     text[] NOT NULL DEFAULT '{}',
    application_mode      text NOT NULL DEFAULT 'APPROVAL_MODE',
    auto_apply_threshold  smallint NOT NULL DEFAULT 80,
    daily_application_cap smallint NOT NULL DEFAULT 10,
    discovery_enabled     boolean NOT NULL DEFAULT true,
    -- Claude scoring runs only when enabled here AND an API key is set,
    -- and only for jobs whose rule-based score reaches the minimum.
    claude_scoring_enabled   boolean NOT NULL DEFAULT false,
    claude_scoring_min_score smallint NOT NULL DEFAULT 60,
    -- NULL: not stated (relocation answers are then flagged for review).
    willing_to_relocate   boolean,
    -- Free-form extras (default answers, notice period, etc.)
    extra                 jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at            timestamptz NOT NULL DEFAULT now(),
    updated_at            timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_settings_single_row CHECK (id = 1),
    CONSTRAINT ck_settings_remote
        CHECK (remote_preference IN ('remote_only', 'hybrid', 'onsite', 'any')),
    CONSTRAINT ck_settings_mode
        CHECK (application_mode IN ('APPROVAL_MODE', 'AUTONOMOUS_MODE')),
    CONSTRAINT ck_settings_threshold CHECK (auto_apply_threshold BETWEEN 0 AND 100),
    CONSTRAINT ck_settings_cap CHECK (daily_application_cap BETWEEN 0 AND 200),
    CONSTRAINT ck_settings_claude_min_score CHECK (claude_scoring_min_score BETWEEN 0 AND 100),
    CONSTRAINT ck_settings_currency CHECK (salary_currency ~ '^[A-Z]{3}$'),
    CONSTRAINT ck_settings_salary
        CHECK ((salary_min IS NULL OR salary_min >= 0) AND (salary_target IS NULL OR salary_target >= 0)),
    CONSTRAINT ck_settings_salary_order
        CHECK (salary_min IS NULL OR salary_target IS NULL OR salary_min <= salary_target),
    CONSTRAINT ck_settings_extra_json CHECK (jsonb_typeof(extra) = 'object')
);
CREATE TRIGGER trg_settings_updated
    BEFORE UPDATE ON settings
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
INSERT INTO settings (id) VALUES (1);

-- ---------------------------------------------------------------------
-- browser_sessions: persisted Playwright storage state per platform
-- ---------------------------------------------------------------------
CREATE TABLE browser_sessions (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    platform      text NOT NULL,
    account_label text NOT NULL DEFAULT 'default',
    -- Playwright storage_state (cookies/localStorage). Sensitive: local DB only.
    storage_state jsonb NOT NULL DEFAULT '{}'::jsonb,
    is_valid      boolean NOT NULL DEFAULT true,
    last_used_at  timestamptz,
    expires_at    timestamptz,
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_browser_sessions_platform CHECK (platform ~ '^[a-z_]+$'),
    CONSTRAINT ck_browser_sessions_label CHECK (btrim(account_label) <> ''),
    CONSTRAINT ck_browser_sessions_state_json CHECK (jsonb_typeof(storage_state) = 'object'),
    CONSTRAINT uq_browser_sessions_platform_account UNIQUE (platform, account_label)
);
CREATE TRIGGER trg_browser_sessions_updated
    BEFORE UPDATE ON browser_sessions
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------
-- llm_cache_entries: Postgres-backed response cache (replaces Redis).
-- Purge rows past expires_at periodically.
-- ---------------------------------------------------------------------
CREATE TABLE llm_cache_entries (
    cache_key     text PRIMARY KEY,
    purpose       text NOT NULL,
    model         text NOT NULL,
    response      jsonb NOT NULL,
    input_tokens  integer NOT NULL DEFAULT 0,
    output_tokens integer NOT NULL DEFAULT 0,
    hit_count     integer NOT NULL DEFAULT 0,
    created_at    timestamptz NOT NULL DEFAULT now(),
    expires_at    timestamptz,
    CONSTRAINT ck_llm_cache_entries_key CHECK (cache_key ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_llm_cache_entries_counts
        CHECK (input_tokens >= 0 AND output_tokens >= 0 AND hit_count >= 0)
);
CREATE INDEX ix_llm_cache_entries_purpose ON llm_cache_entries (purpose);
CREATE INDEX ix_llm_cache_entries_expires_at
    ON llm_cache_entries (expires_at) WHERE expires_at IS NOT NULL;

-- ---------------------------------------------------------------------
-- discovery_runs: one row per job-board crawl (monitoring). Counters are
-- totals over all companies crawled; details holds per-company results.
-- ---------------------------------------------------------------------
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

-- ---------------------------------------------------------------------
-- application_submissions / automation_logs: browser runs that fill an
-- approved package (approval mode only) and their structured logs.
-- ---------------------------------------------------------------------

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
