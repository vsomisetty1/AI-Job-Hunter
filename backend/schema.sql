-- =====================================================================
-- AI Job Hunter - PostgreSQL schema (PostgreSQL 14+)
--
-- Single source of truth for DDL. Alembic migration 0001 executes this
-- file, and the SQLAlchemy models in app/models mirror it.
-- NOTE: do not use the percent character in this file (the migration
-- runs it through the raw driver).
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
    -- Agent 1 output: trajectory, rationale, etc.
    inference        jsonb NOT NULL DEFAULT '{}'::jsonb,
    seniority        text,
    experience_level text,
    years_experience numeric(4,1),
    primary_roles    text[] NOT NULL DEFAULT '{}',
    related_roles    text[] NOT NULL DEFAULT '{}',
    industries       text[] NOT NULL DEFAULT '{}',
    is_active        boolean NOT NULL DEFAULT true,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_candidate_profiles_years
        CHECK (years_experience IS NULL OR (years_experience >= 0 AND years_experience <= 70)),
    CONSTRAINT ck_candidate_profiles_email
        CHECK (email IS NULL OR position('@' in email) > 1)
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
    profile_id   uuid NOT NULL REFERENCES candidate_profiles(id) ON DELETE CASCADE,
    filename     text NOT NULL,
    file_type    text NOT NULL,
    storage_path text NOT NULL,
    content_hash char(64) NOT NULL,
    raw_text     text,
    parsed_at    timestamptz,
    is_primary   boolean NOT NULL DEFAULT false,
    created_at   timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_resumes_file_type CHECK (file_type IN ('pdf', 'docx')),
    CONSTRAINT ck_resumes_content_hash CHECK (content_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT uq_resumes_profile_hash UNIQUE (profile_id, content_hash)
);
CREATE INDEX ix_resumes_profile_id ON resumes (profile_id);
CREATE UNIQUE INDEX uq_resumes_one_primary
    ON resumes (profile_id) WHERE is_primary;

-- ---------------------------------------------------------------------
-- jobs: normalized postings from all connectors
-- ---------------------------------------------------------------------
CREATE TABLE jobs (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source           text NOT NULL,
    external_id      text NOT NULL,
    company          text NOT NULL,
    company_slug     text NOT NULL,
    title            text NOT NULL,
    location         text,
    remote_type      text NOT NULL DEFAULT 'unknown',
    employment_type  text,
    salary_min       integer,
    salary_max       integer,
    salary_currency  char(3),
    compensation_text text,
    description      text NOT NULL DEFAULT '',
    requirements     jsonb NOT NULL DEFAULT '[]'::jsonb,
    url              text NOT NULL,
    apply_url        text,
    -- Hash of normalized company + title + location (cross-source dedup).
    -- Deliberately NOT unique: one company may post identical titles.
    dedup_key        char(64) NOT NULL,
    status           text NOT NULL DEFAULT 'new',
    filter_reason    text,
    posted_at        timestamptz,
    first_seen_at    timestamptz NOT NULL DEFAULT now(),
    last_seen_at     timestamptz NOT NULL DEFAULT now(),
    raw              jsonb,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_jobs_source CHECK (source ~ '^[a-z_]+$'),
    CONSTRAINT ck_jobs_remote_type
        CHECK (remote_type IN ('remote', 'hybrid', 'onsite', 'unknown')),
    CONSTRAINT ck_jobs_status
        CHECK (status IN ('new', 'filtered', 'scored', 'shortlisted', 'skipped', 'applied', 'expired')),
    CONSTRAINT ck_jobs_salary_range
        CHECK (salary_min IS NULL OR salary_max IS NULL OR salary_min <= salary_max),
    CONSTRAINT ck_jobs_salary_nonneg
        CHECK ((salary_min IS NULL OR salary_min >= 0) AND (salary_max IS NULL OR salary_max >= 0)),
    CONSTRAINT ck_jobs_dedup_key CHECK (dedup_key ~ '^[0-9a-f]{64}$'),
    CONSTRAINT uq_jobs_source_external UNIQUE (source, external_id),
    CONSTRAINT uq_jobs_url UNIQUE (url)
);
CREATE INDEX ix_jobs_status ON jobs (status);
CREATE INDEX ix_jobs_dedup_key ON jobs (dedup_key);
CREATE INDEX ix_jobs_company_lower ON jobs (lower(company));
CREATE INDEX ix_jobs_source_slug ON jobs (source, company_slug);
CREATE INDEX ix_jobs_posted_at ON jobs (posted_at DESC NULLS LAST);
CREATE INDEX ix_jobs_last_seen_at ON jobs (last_seen_at);
CREATE TRIGGER trg_jobs_updated
    BEFORE UPDATE ON jobs
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------
-- resume_versions: original snapshot + per-job tailored versions
-- ---------------------------------------------------------------------
CREATE TABLE resume_versions (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    resume_id      uuid NOT NULL REFERENCES resumes(id) ON DELETE CASCADE,
    job_id         uuid REFERENCES jobs(id) ON DELETE CASCADE,
    kind           text NOT NULL DEFAULT 'tailored',
    version_number integer NOT NULL DEFAULT 1,
    -- Structured resume content used by the PDF/DOCX generators
    content        jsonb NOT NULL DEFAULT '{}'::jsonb,
    pdf_path       text,
    docx_path      text,
    ats_keywords   text[] NOT NULL DEFAULT '{}',
    change_summary text,
    created_at     timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_resume_versions_kind CHECK (kind IN ('original', 'tailored')),
    CONSTRAINT ck_resume_versions_version CHECK (version_number >= 1),
    CONSTRAINT ck_resume_versions_tailored_has_job
        CHECK (kind = 'original' OR job_id IS NOT NULL),
    CONSTRAINT uq_resume_versions_resume_job_version
        UNIQUE (resume_id, job_id, version_number)
);
CREATE INDEX ix_resume_versions_resume_id ON resume_versions (resume_id);
CREATE INDEX ix_resume_versions_job_id ON resume_versions (job_id);

-- ---------------------------------------------------------------------
-- job_scores: Claude scoring output (cached per prompt version)
-- ---------------------------------------------------------------------
CREATE TABLE job_scores (
    id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id                uuid NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    profile_id            uuid NOT NULL REFERENCES candidate_profiles(id) ON DELETE CASCADE,
    overall_score         smallint NOT NULL,
    interview_probability smallint NOT NULL,
    salary_score          smallint NOT NULL,
    growth_score          smallint NOT NULL,
    company_score         smallint NOT NULL,
    rationale             text,
    matched_skills        jsonb NOT NULL DEFAULT '[]'::jsonb,
    missing_skills        jsonb NOT NULL DEFAULT '[]'::jsonb,
    model                 text NOT NULL,
    prompt_version        text NOT NULL,
    input_tokens          integer NOT NULL DEFAULT 0,
    output_tokens         integer NOT NULL DEFAULT 0,
    created_at            timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_job_scores_overall CHECK (overall_score BETWEEN 0 AND 100),
    CONSTRAINT ck_job_scores_interview CHECK (interview_probability BETWEEN 0 AND 100),
    CONSTRAINT ck_job_scores_salary CHECK (salary_score BETWEEN 0 AND 100),
    CONSTRAINT ck_job_scores_growth CHECK (growth_score BETWEEN 0 AND 100),
    CONSTRAINT ck_job_scores_company CHECK (company_score BETWEEN 0 AND 100),
    CONSTRAINT ck_job_scores_tokens CHECK (input_tokens >= 0 AND output_tokens >= 0),
    CONSTRAINT uq_job_scores_job_profile_prompt UNIQUE (job_id, profile_id, prompt_version)
);
CREATE INDEX ix_job_scores_profile_overall ON job_scores (profile_id, overall_score DESC);
CREATE INDEX ix_job_scores_job_id ON job_scores (job_id);

-- ---------------------------------------------------------------------
-- cover_letters: one per job per profile (regeneration overwrites)
-- ---------------------------------------------------------------------
CREATE TABLE cover_letters (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id     uuid NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    profile_id uuid NOT NULL REFERENCES candidate_profiles(id) ON DELETE CASCADE,
    content    text NOT NULL,
    pdf_path   text,
    docx_path  text,
    model      text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_cover_letters_job_profile UNIQUE (job_id, profile_id)
);
CREATE INDEX ix_cover_letters_profile_id ON cover_letters (profile_id);
CREATE TRIGGER trg_cover_letters_updated
    BEFORE UPDATE ON cover_letters
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------
-- applications: lifecycle tracking + automation state
-- ---------------------------------------------------------------------
CREATE TABLE applications (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id            uuid NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    profile_id        uuid NOT NULL REFERENCES candidate_profiles(id) ON DELETE CASCADE,
    resume_version_id uuid REFERENCES resume_versions(id) ON DELETE SET NULL,
    cover_letter_id   uuid REFERENCES cover_letters(id) ON DELETE SET NULL,
    -- User-visible pipeline status
    status            text NOT NULL DEFAULT 'drafted',
    -- Automation progress (separate so status stays the six tracked stages)
    automation_state  text NOT NULL DEFAULT 'pending',
    mode              text NOT NULL DEFAULT 'APPROVAL_MODE',
    platform          text NOT NULL,
    match_score       smallint,
    -- Failure recovery: last completed step, form progress, etc.
    checkpoint        jsonb NOT NULL DEFAULT '{}'::jsonb,
    attempts          integer NOT NULL DEFAULT 0,
    last_error        text,
    confirmation_ref  text,
    notes             text,
    status_history    jsonb NOT NULL DEFAULT '[]'::jsonb,
    approved_at       timestamptz,
    submitted_at      timestamptz,
    status_updated_at timestamptz NOT NULL DEFAULT now(),
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_applications_status
        CHECK (status IN ('drafted', 'ready', 'submitted', 'interview', 'rejected', 'offer')),
    CONSTRAINT ck_applications_automation_state
        CHECK (automation_state IN ('pending', 'in_progress', 'needs_manual', 'failed', 'completed')),
    CONSTRAINT ck_applications_mode
        CHECK (mode IN ('APPROVAL_MODE', 'AUTONOMOUS_MODE')),
    CONSTRAINT ck_applications_platform CHECK (platform ~ '^[a-z_]+$'),
    CONSTRAINT ck_applications_match_score
        CHECK (match_score IS NULL OR match_score BETWEEN 0 AND 100),
    CONSTRAINT ck_applications_attempts CHECK (attempts >= 0),
    CONSTRAINT ck_applications_submitted_at
        CHECK (status IN ('drafted', 'ready') OR submitted_at IS NOT NULL),
    CONSTRAINT uq_applications_job_profile UNIQUE (job_id, profile_id)
);
CREATE INDEX ix_applications_status ON applications (status);
CREATE INDEX ix_applications_automation_state ON applications (automation_state);
CREATE INDEX ix_applications_job_id ON applications (job_id);
CREATE INDEX ix_applications_submitted_at ON applications (submitted_at DESC NULLS LAST);
CREATE TRIGGER trg_applications_updated
    BEFORE UPDATE ON applications
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------
-- application_answers: generated/entered answers to form questions
-- ---------------------------------------------------------------------
CREATE TABLE application_answers (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    application_id uuid NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
    question       text NOT NULL,
    -- sha256 of the normalized question text
    question_hash  char(64) NOT NULL,
    -- Canonical key when recognised, e.g. work_authorization
    question_key   text,
    answer         text NOT NULL,
    source         text NOT NULL,
    confidence     numeric(3,2),
    needs_review   boolean NOT NULL DEFAULT false,
    created_at     timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_application_answers_source
        CHECK (source IN ('profile', 'settings', 'llm', 'user')),
    CONSTRAINT ck_application_answers_confidence
        CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    CONSTRAINT ck_application_answers_hash CHECK (question_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT uq_application_answers_app_question UNIQUE (application_id, question_hash)
);
CREATE INDEX ix_application_answers_application_id ON application_answers (application_id);
CREATE INDEX ix_application_answers_needs_review
    ON application_answers (application_id) WHERE needs_review;

-- ---------------------------------------------------------------------
-- agent_runs: audit log + token/cost accounting
-- ---------------------------------------------------------------------
CREATE TABLE agent_runs (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_name     text NOT NULL,
    status         text NOT NULL DEFAULT 'running',
    job_id         uuid REFERENCES jobs(id) ON DELETE SET NULL,
    application_id uuid REFERENCES applications(id) ON DELETE SET NULL,
    input_summary  jsonb NOT NULL DEFAULT '{}'::jsonb,
    output_summary jsonb NOT NULL DEFAULT '{}'::jsonb,
    error          text,
    input_tokens   integer NOT NULL DEFAULT 0,
    output_tokens  integer NOT NULL DEFAULT 0,
    cost_usd       numeric(10,6) NOT NULL DEFAULT 0,
    started_at     timestamptz NOT NULL DEFAULT now(),
    finished_at    timestamptz,
    duration_ms    integer,
    CONSTRAINT ck_agent_runs_status
        CHECK (status IN ('running', 'succeeded', 'failed', 'cancelled')),
    CONSTRAINT ck_agent_runs_tokens CHECK (input_tokens >= 0 AND output_tokens >= 0),
    CONSTRAINT ck_agent_runs_cost CHECK (cost_usd >= 0),
    CONSTRAINT ck_agent_runs_finished
        CHECK (finished_at IS NULL OR finished_at >= started_at)
);
CREATE INDEX ix_agent_runs_agent_started ON agent_runs (agent_name, started_at DESC);
CREATE INDEX ix_agent_runs_status ON agent_runs (status);
CREATE INDEX ix_agent_runs_job_id ON agent_runs (job_id);
CREATE INDEX ix_agent_runs_application_id ON agent_runs (application_id);

-- ---------------------------------------------------------------------
-- settings: single-row user preferences
-- ---------------------------------------------------------------------
CREATE TABLE settings (
    id                    smallint PRIMARY KEY DEFAULT 1,
    preferred_locations   text[] NOT NULL DEFAULT '{}',
    remote_preference     text NOT NULL DEFAULT 'any',
    job_types             text[] NOT NULL DEFAULT '{}',
    salary_min            integer,
    salary_target         integer,
    salary_currency       char(3) NOT NULL DEFAULT 'USD',
    work_authorization    text,
    visa_status           text,
    requires_sponsorship  boolean NOT NULL DEFAULT false,
    excluded_companies    text[] NOT NULL DEFAULT '{}',
    excluded_keywords     text[] NOT NULL DEFAULT '{}',
    application_mode      text NOT NULL DEFAULT 'APPROVAL_MODE',
    auto_apply_threshold  smallint NOT NULL DEFAULT 80,
    daily_application_cap smallint NOT NULL DEFAULT 10,
    discovery_enabled     boolean NOT NULL DEFAULT true,
    -- [{"source": "greenhouse", "slug": "stripe", "name": "Stripe"}, ...]
    tracked_companies     jsonb NOT NULL DEFAULT '[]'::jsonb,
    -- Free-form extras (default answers, notice period, etc.)
    extra                 jsonb NOT NULL DEFAULT '{}'::jsonb,
    updated_at            timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_settings_single_row CHECK (id = 1),
    CONSTRAINT ck_settings_remote
        CHECK (remote_preference IN ('remote_only', 'hybrid', 'onsite', 'any')),
    CONSTRAINT ck_settings_mode
        CHECK (application_mode IN ('APPROVAL_MODE', 'AUTONOMOUS_MODE')),
    CONSTRAINT ck_settings_threshold CHECK (auto_apply_threshold BETWEEN 0 AND 100),
    CONSTRAINT ck_settings_cap CHECK (daily_application_cap BETWEEN 0 AND 200),
    CONSTRAINT ck_settings_salary
        CHECK ((salary_min IS NULL OR salary_min >= 0)
               AND (salary_target IS NULL OR salary_target >= 0))
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
    CONSTRAINT uq_browser_sessions_platform_account UNIQUE (platform, account_label)
);
CREATE TRIGGER trg_browser_sessions_updated
    BEFORE UPDATE ON browser_sessions
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------
-- llm_cache: Postgres-backed response cache (replaces Redis)
-- ---------------------------------------------------------------------
CREATE TABLE llm_cache (
    cache_key     char(64) PRIMARY KEY,
    purpose       text NOT NULL,
    model         text NOT NULL,
    response      jsonb NOT NULL,
    input_tokens  integer NOT NULL DEFAULT 0,
    output_tokens integer NOT NULL DEFAULT 0,
    hit_count     integer NOT NULL DEFAULT 0,
    created_at    timestamptz NOT NULL DEFAULT now(),
    expires_at    timestamptz,
    CONSTRAINT ck_llm_cache_key CHECK (cache_key ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_llm_cache_counts
        CHECK (input_tokens >= 0 AND output_tokens >= 0 AND hit_count >= 0)
);
CREATE INDEX ix_llm_cache_purpose ON llm_cache (purpose);
CREATE INDEX ix_llm_cache_expires_at ON llm_cache (expires_at) WHERE expires_at IS NOT NULL;
