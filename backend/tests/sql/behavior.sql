-- Behavioural checks for the schema. Run against a migrated, EMPTY database.
-- Everything happens inside one transaction that is rolled back.
-- Any failed expectation raises an exception (non-zero exit with ON_ERROR_STOP).
-- No percent characters (script may be run through a raw driver).
BEGIN;

CREATE FUNCTION pg_temp.expect_error(stmt text, label text, vars jsonb DEFAULT '{}'::jsonb)
RETURNS void AS $$
DECLARE
    k text;
    v text;
BEGIN
    FOR k, v IN SELECT * FROM jsonb_each_text(vars) LOOP
        stmt := replace(stmt, '{' || k || '}', v);
    END LOOP;
    BEGIN
        EXECUTE stmt;
    EXCEPTION WHEN integrity_constraint_violation THEN
        RETURN;
    END;
    RAISE EXCEPTION USING MESSAGE = 'EXPECTED constraint violation but statement succeeded: ' || label;
END;
$$ LANGUAGE plpgsql;

CREATE FUNCTION pg_temp.expect_true(cond boolean, label text) RETURNS void AS $$
BEGIN
    IF cond IS NOT TRUE THEN
        RAISE EXCEPTION USING MESSAGE = 'ASSERTION FAILED: ' || label;
    END IF;
END;
$$ LANGUAGE plpgsql;

DO $$
DECLARE
    p uuid; r uuid; c uuid; j1 uuid; j2 uuid; rv1 uuid; rv2 uuid; s1 uuid; cl1 uuid; a1 uuid;
    h text := repeat('a', 64);
    v jsonb;
    n int;
BEGIN
    -- ---------------------------------------------------------- settings
    PERFORM pg_temp.expect_true((SELECT count(*) FROM settings) = 1, 'settings seeded with one row');
    PERFORM pg_temp.expect_error('INSERT INTO settings (id) VALUES (2)', 'settings single row');
    PERFORM pg_temp.expect_error('UPDATE settings SET salary_min = 200, salary_target = 100', 'salary order');
    PERFORM pg_temp.expect_error('UPDATE settings SET auto_apply_threshold = 101', 'threshold range');
    PERFORM pg_temp.expect_error('UPDATE settings SET salary_currency = ''usd''', 'currency uppercase');
    PERFORM pg_temp.expect_error('UPDATE settings SET application_mode = ''YOLO''', 'mode enum');

    -- ---------------------------------------------------------- profiles
    INSERT INTO candidate_profiles (full_name, email) VALUES ('Ada Lovelace', 'ada@example.com') RETURNING id INTO p;
    PERFORM pg_temp.expect_error('INSERT INTO candidate_profiles (full_name) VALUES (''Second Active'')', 'single active profile');
    PERFORM pg_temp.expect_error('INSERT INTO candidate_profiles (full_name, is_active) VALUES ('' '', false)', 'blank name');
    PERFORM pg_temp.expect_error('INSERT INTO candidate_profiles (full_name, email, is_active) VALUES (''B'', ''nope'', false)', 'bad email');
    PERFORM pg_temp.expect_error('INSERT INTO candidate_profiles (full_name, years_experience, is_active) VALUES (''B'', 99, false)', 'years range');
    PERFORM pg_temp.expect_error('INSERT INTO candidate_profiles (full_name, profile, is_active) VALUES (''B'', ''[]''::jsonb, false)', 'profile must be object');

    -- ---------------------------------------------------------- resumes
    INSERT INTO resumes (profile_id, filename, file_type, storage_path, content_hash, is_primary)
        VALUES (p, 'cv.pdf', 'pdf', 'resumes/cv.pdf', h, true) RETURNING id INTO r;
    v := jsonb_build_object('p', p::text, 'h', repeat('b', 64));
    PERFORM pg_temp.expect_error('INSERT INTO resumes (profile_id, filename, file_type, storage_path, content_hash) VALUES (''{p}'', ''x.pdf'', ''pdf'', ''resumes/cv.pdf'', ''{h}'')', 'unique storage_path', v);
    PERFORM pg_temp.expect_error('INSERT INTO resumes (profile_id, filename, file_type, storage_path, content_hash, is_primary) VALUES (''{p}'', ''y.pdf'', ''pdf'', ''resumes/y.pdf'', ''{h}'', false)', 'unique content hash per profile', jsonb_build_object('p', p::text, 'h', h));
    PERFORM pg_temp.expect_error('INSERT INTO resumes (profile_id, filename, file_type, storage_path, content_hash, is_primary) VALUES (''{p}'', ''z.pdf'', ''pdf'', ''resumes/z.pdf'', ''{h}'', true)', 'one primary resume', v);
    PERFORM pg_temp.expect_error('INSERT INTO resumes (profile_id, filename, file_type, storage_path, content_hash) VALUES (''{p}'', ''z.txt'', ''txt'', ''resumes/z.txt'', ''{h}'')', 'file type enum', v);
    PERFORM pg_temp.expect_error('INSERT INTO resumes (profile_id, filename, file_type, storage_path, content_hash, parse_status) VALUES (''{p}'', ''s.pdf'', ''pdf'', ''resumes/s.pdf'', repeat(''c'', 64), ''parsed'')', 'parsed resume needs parsed_at', v);
    PERFORM pg_temp.expect_error('INSERT INTO resumes (profile_id, filename, file_type, storage_path, content_hash, parse_status) VALUES (''{p}'', ''s.pdf'', ''pdf'', ''resumes/s.pdf'', repeat(''c'', 64), ''weird'')', 'parse status enum', v);
    PERFORM pg_temp.expect_error('INSERT INTO resumes (profile_id, filename, file_type, storage_path, content_hash, size_bytes) VALUES (''{p}'', ''s.pdf'', ''pdf'', ''resumes/s.pdf'', repeat(''c'', 64), -1)', 'size non-negative', v);
    PERFORM pg_temp.expect_error('UPDATE candidate_profiles SET inference_status = ''bogus'' WHERE id = ''{p}''', 'inference status enum', v);
    PERFORM pg_temp.expect_error('INSERT INTO resumes (profile_id, filename, file_type, storage_path, content_hash) VALUES (gen_random_uuid(), ''z.pdf'', ''pdf'', ''resumes/q.pdf'', ''{h}'')', 'resume needs real profile', v);

    -- ---------------------------------------------------------- companies
    INSERT INTO companies (name, source, slug) VALUES ('Acme', 'greenhouse', 'acme') RETURNING id INTO c;
    PERFORM pg_temp.expect_error('INSERT INTO companies (name, source, slug) VALUES (''Acme 2'', ''greenhouse'', ''acme'')', 'unique source+slug');
    PERFORM pg_temp.expect_error('INSERT INTO companies (name, source, slug) VALUES (''X'', ''Green House'', ''x'')', 'source format');
    PERFORM pg_temp.expect_error('INSERT INTO companies (name, source, slug, consecutive_failures) VALUES (''X'', ''lever'', ''x'', -1)', 'failures non-negative');

    -- ---------------------------------------------------------- jobs
    INSERT INTO jobs (company_id, external_id, title, url, dedup_key) VALUES (c, '1', 'Engineer', 'https://x.test/1', h) RETURNING id INTO j1;
    INSERT INTO jobs (company_id, external_id, title, url, dedup_key) VALUES (c, '2', 'Designer', 'https://x.test/2', h) RETURNING id INTO j2;
    v := jsonb_build_object('c', c::text, 'h', h);
    PERFORM pg_temp.expect_error('INSERT INTO jobs (company_id, external_id, title, url, dedup_key) VALUES (''{c}'', ''1'', ''Dup'', ''https://x.test/9'', ''{h}'')', 'unique company+external_id', v);
    PERFORM pg_temp.expect_error('INSERT INTO jobs (company_id, external_id, title, url, dedup_key) VALUES (''{c}'', ''9'', ''Dup'', ''https://x.test/1'', ''{h}'')', 'unique url', v);
    PERFORM pg_temp.expect_error('INSERT INTO jobs (company_id, external_id, title, url, dedup_key) VALUES (gen_random_uuid(), ''9'', ''T'', ''https://x.test/9'', ''{h}'')', 'job needs real company', v);
    PERFORM pg_temp.expect_error('INSERT INTO jobs (company_id, external_id, title, url, dedup_key, remote_type) VALUES (''{c}'', ''9'', ''T'', ''https://x.test/9'', ''{h}'', ''moon'')', 'remote_type enum', v);
    PERFORM pg_temp.expect_error('INSERT INTO jobs (company_id, external_id, title, url, dedup_key) VALUES (''{c}'', ''9'', ''T'', ''ftp://x.test/9'', ''{h}'')', 'url scheme', v);
    PERFORM pg_temp.expect_error('INSERT INTO jobs (company_id, external_id, title, url, dedup_key, salary_min, salary_max) VALUES (''{c}'', ''9'', ''T'', ''https://x.test/9'', ''{h}'', 200, 100)', 'salary range', v);
    PERFORM pg_temp.expect_error('INSERT INTO jobs (company_id, external_id, title, url, dedup_key, salary_currency) VALUES (''{c}'', ''9'', ''T'', ''https://x.test/9'', ''{h}'', ''usd'')', 'currency uppercase', v);
    PERFORM pg_temp.expect_error('INSERT INTO jobs (company_id, external_id, title, url, dedup_key, requirements) VALUES (''{c}'', ''9'', ''T'', ''https://x.test/9'', ''{h}'', ''{}''::jsonb)', 'requirements must be array', v);
    PERFORM pg_temp.expect_error('INSERT INTO jobs (company_id, external_id, title, url, dedup_key) VALUES (''{c}'', ''9'', '' '', ''https://x.test/9'', ''{h}'')', 'blank title', v);
    PERFORM pg_temp.expect_error('INSERT INTO jobs (company_id, external_id, title, url, dedup_key, first_seen_at, last_seen_at) VALUES (''{c}'', ''9'', ''T'', ''https://x.test/9'', ''{h}'', now(), now() - interval ''1 day'')', 'last_seen >= first_seen', v);
    PERFORM pg_temp.expect_error('DELETE FROM companies WHERE id = ''{c}''', 'company delete restricted while jobs exist', v);

    -- ------------------------------------------------- job discovery (0003)
    PERFORM pg_temp.expect_error('UPDATE jobs SET expired_at = now() WHERE id = ''{j}''', 'expired_at only for expired jobs', jsonb_build_object('j', j1::text));
    UPDATE jobs SET status = 'expired', expired_at = now() WHERE id = j2;
    UPDATE jobs SET status = 'new', expired_at = NULL WHERE id = j2;
    PERFORM pg_temp.expect_error('UPDATE jobs SET content_hash = ''xyz'' WHERE id = ''{j}''', 'content hash format', jsonb_build_object('j', j1::text));
    INSERT INTO discovery_runs (trigger) VALUES ('manual');
    PERFORM pg_temp.expect_error('INSERT INTO discovery_runs (trigger) VALUES (''scheduled'')', 'one running discovery at a time');
    PERFORM pg_temp.expect_error('UPDATE discovery_runs SET status = ''succeeded''', 'finished run needs finished_at');
    UPDATE discovery_runs SET status = 'succeeded', finished_at = now(), jobs_found = 3;
    INSERT INTO discovery_runs (trigger) VALUES ('scheduled');
    PERFORM pg_temp.expect_error('INSERT INTO discovery_runs (trigger, status, finished_at) VALUES (''cron'', ''failed'', now())', 'trigger enum');
    PERFORM pg_temp.expect_error('UPDATE discovery_runs SET jobs_inserted = -1 WHERE status = ''running''', 'counters non-negative');
    DELETE FROM discovery_runs;

    -- ---------------------------------------------------------- artifacts
    INSERT INTO resume_versions (resume_id, job_id, version_number) VALUES (r, j1, 1) RETURNING id INTO rv1;
    INSERT INTO resume_versions (resume_id, job_id, version_number) VALUES (r, j2, 2) RETURNING id INTO rv2;
    INSERT INTO resume_versions (resume_id, kind, source, version_number) VALUES (r, 'original', 'upload', 3);
    INSERT INTO resume_versions (resume_id, kind, source, version_number) VALUES (r, 'parsed', 'parser', 4);
    INSERT INTO resume_versions (resume_id, kind, target_role, version_number) VALUES (r, 'tailored', 'Data Engineer', 5);
    v := jsonb_build_object('r', r::text, 'j', j1::text);
    PERFORM pg_temp.expect_error('INSERT INTO resume_versions (resume_id, job_id, version_number) VALUES (''{r}'', ''{j}'', 1)', 'unique resume+version', v);
    PERFORM pg_temp.expect_error('INSERT INTO resume_versions (resume_id, kind, version_number) VALUES (''{r}'', ''draft'', 9)', 'version kind enum', v);
    PERFORM pg_temp.expect_error('INSERT INTO resume_versions (resume_id, source, version_number) VALUES (''{r}'', ''magic'', 9)', 'version source enum', v);
    PERFORM pg_temp.expect_error('INSERT INTO resume_versions (resume_id, version_number) VALUES (''{r}'', 9)', 'tailored version needs a target', v);
    PERFORM pg_temp.expect_error('INSERT INTO resume_versions (resume_id, kind, source, job_id, version_number) VALUES (''{r}'', ''parsed'', ''parser'', ''{j}'', 9)', 'parsed version cannot target a job', v);
    PERFORM pg_temp.expect_error('INSERT INTO resume_versions (resume_id, kind, source, target_company, version_number) VALUES (''{r}'', ''original'', ''upload'', ''Acme'', 9)', 'original version cannot target a company', v);
    PERFORM pg_temp.expect_error('INSERT INTO resume_versions (resume_id, kind, target_role, version_number) VALUES (''{r}'', ''tailored'', '' '', 9)', 'blank target role', v);
    PERFORM pg_temp.expect_error('INSERT INTO resume_versions (resume_id, job_id, version_number) VALUES (''{r}'', ''{j}'', 0)', 'version >= 1', jsonb_build_object('r', r::text, 'j', j1::text));

    INSERT INTO job_scores (job_id, profile_id, overall_score, interview_probability, salary_score, growth_score, company_score, model, prompt_version)
        VALUES (j1, p, 80, 40, 70, 60, 75, 'm', 'v1') RETURNING id INTO s1;
    v := jsonb_build_object('j', j1::text, 'p', p::text);
    PERFORM pg_temp.expect_error('INSERT INTO job_scores (job_id, profile_id, overall_score, interview_probability, salary_score, growth_score, company_score, model, prompt_version) VALUES (''{j}'', ''{p}'', 101, 1, 1, 1, 1, ''m'', ''v9'')', 'score <= 100', v);
    PERFORM pg_temp.expect_error('INSERT INTO job_scores (job_id, profile_id, overall_score, interview_probability, salary_score, growth_score, company_score, model, prompt_version) VALUES (''{j}'', ''{p}'', 1, 1, 1, 1, 1, ''m'', ''v1'')', 'unique score per prompt version', v);
    PERFORM pg_temp.expect_error('INSERT INTO job_scores (job_id, profile_id, overall_score, interview_probability, salary_score, growth_score, company_score, model, prompt_version, matched_skills) VALUES (''{j}'', ''{p}'', 1, 1, 1, 1, 1, ''m'', ''v8'', ''{}''::jsonb)', 'skills must be array', v);

    INSERT INTO cover_letters (job_id, profile_id, content) VALUES (j1, p, 'Dear team') RETURNING id INTO cl1;
    PERFORM pg_temp.expect_error('INSERT INTO cover_letters (job_id, profile_id, content) VALUES (''{j}'', ''{p}'', ''again'')', 'one cover letter per job+profile', v);

    -- ---------------------------------------------------------- applications
    INSERT INTO applications (job_id, profile_id, resume_version_id, cover_letter_id, job_score_id)
        VALUES (j1, p, rv1, cl1, s1) RETURNING id INTO a1;
    PERFORM pg_temp.expect_error('INSERT INTO applications (job_id, profile_id) VALUES (''{j}'', ''{p}'')', 'one application per job+profile', v);
    -- artifact from a DIFFERENT job must be rejected by the composite FK
    PERFORM pg_temp.expect_error('INSERT INTO applications (job_id, profile_id, resume_version_id) VALUES (''{j2}'', ''{p}'', ''{rv1}'')', 'resume version must belong to same job', jsonb_build_object('j2', j2::text, 'p', p::text, 'rv1', rv1::text));
    PERFORM pg_temp.expect_error('UPDATE applications SET resume_version_id = ''{rv2}'' WHERE id = ''{a}''', 'cannot repoint to other-job resume version', jsonb_build_object('rv2', rv2::text, 'a', a1::text));
    PERFORM pg_temp.expect_error('UPDATE applications SET status = ''submitted'' WHERE id = ''{a}''', 'submitted needs submitted_at', jsonb_build_object('a', a1::text));
    PERFORM pg_temp.expect_error('UPDATE applications SET automation_state = ''completed'' WHERE id = ''{a}''', 'completed needs submitted_at', jsonb_build_object('a', a1::text));
    PERFORM pg_temp.expect_error('UPDATE applications SET status = ''hired'' WHERE id = ''{a}''', 'status enum', jsonb_build_object('a', a1::text));
    PERFORM pg_temp.expect_error('UPDATE applications SET attempts = -1 WHERE id = ''{a}''', 'attempts non-negative', jsonb_build_object('a', a1::text));
    PERFORM pg_temp.expect_error('DELETE FROM jobs WHERE id = ''{j}''', 'job delete restricted while application exists', v);

    -- deleting an artifact nulls ONLY the artifact column (job_id stays)
    DELETE FROM resume_versions WHERE id = rv1;
    PERFORM pg_temp.expect_true((SELECT resume_version_id IS NULL AND job_id = j1 FROM applications WHERE id = a1), 'SET NULL (column) keeps job_id');
    DELETE FROM cover_letters WHERE id = cl1;
    DELETE FROM job_scores WHERE id = s1;
    PERFORM pg_temp.expect_true((SELECT cover_letter_id IS NULL AND job_score_id IS NULL AND job_id = j1 FROM applications WHERE id = a1), 'other artifacts null too');

    -- ---------------------------------------------------------- events / answers
    INSERT INTO application_events (application_id, event_type, to_status, actor) VALUES (a1, 'created', 'drafted', 'system');
    PERFORM pg_temp.expect_error('INSERT INTO application_events (application_id, event_type) VALUES (''{a}'', ''exploded'')', 'event type enum', jsonb_build_object('a', a1::text));
    PERFORM pg_temp.expect_error('INSERT INTO application_events (application_id, event_type, to_status) VALUES (''{a}'', ''note'', ''hired'')', 'event status enum', jsonb_build_object('a', a1::text));
    INSERT INTO application_answers (application_id, question, question_hash, answer, source) VALUES (a1, 'Q?', h, 'A', 'profile');
    PERFORM pg_temp.expect_error('INSERT INTO application_answers (application_id, question, question_hash, answer, source) VALUES (''{a}'', ''Q?'', ''{h}'', ''B'', ''llm'')', 'one answer per question', jsonb_build_object('a', a1::text, 'h', h));
    PERFORM pg_temp.expect_error('INSERT INTO application_answers (application_id, question, question_hash, answer, source, confidence) VALUES (''{a}'', ''Q2'', ''{h2}'', ''B'', ''llm'', 1.5)', 'confidence range', jsonb_build_object('a', a1::text, 'h2', repeat('c', 64)));

    -- ---------------------------------------------------------- agent_runs
    PERFORM pg_temp.expect_error('INSERT INTO agent_runs (agent_name, status) VALUES (''x'', ''succeeded'')', 'finished run needs finished_at');
    PERFORM pg_temp.expect_error('INSERT INTO agent_runs (agent_name, status, started_at, finished_at) VALUES (''x'', ''failed'', now(), now() - interval ''1 hour'')', 'finish after start');
    PERFORM pg_temp.expect_error('INSERT INTO agent_runs (agent_name, cost_usd) VALUES (''x'', -1)', 'cost non-negative');
    INSERT INTO agent_runs (agent_name, job_id, application_id) VALUES ('job_scoring', j1, a1);

    -- ---------------------------------------------------------- cache, sessions
    PERFORM pg_temp.expect_error('INSERT INTO llm_cache_entries (cache_key, purpose, model, response) VALUES (''short'', ''p'', ''m'', ''{}''::jsonb)', 'cache key format');
    INSERT INTO browser_sessions (platform, account_label) VALUES ('greenhouse', 'default');
    PERFORM pg_temp.expect_error('INSERT INTO browser_sessions (platform, account_label) VALUES (''greenhouse'', ''default'')', 'one session per platform+account');

    -- ---------------------------------------------------------- triggers
    UPDATE jobs SET title = 'Engineer II', updated_at = now() - interval '1 day' WHERE id = j1;
    PERFORM pg_temp.expect_true((SELECT updated_at = now() FROM jobs WHERE id = j1), 'updated_at trigger overrides manual value');
    UPDATE settings SET remote_preference = 'hybrid';
    PERFORM pg_temp.expect_true((SELECT updated_at = now() FROM settings WHERE id = 1), 'settings updated_at trigger');

    -- ---------------------------------------------------------- cascades
    DELETE FROM applications WHERE id = a1;
    SELECT count(*) INTO n FROM application_events WHERE application_id = a1;
    PERFORM pg_temp.expect_true(n = 0, 'events cascade with application');
    PERFORM pg_temp.expect_true((SELECT application_id IS NULL FROM agent_runs WHERE agent_name = 'job_scoring'), 'agent_runs SET NULL on application delete');
    DELETE FROM jobs WHERE id = j2;
    PERFORM pg_temp.expect_true((SELECT count(*) FROM resume_versions WHERE job_id = j2) = 0, 'resume versions cascade with job');
    DELETE FROM candidate_profiles WHERE id = p;
    PERFORM pg_temp.expect_true((SELECT count(*) FROM resumes) = 0, 'resumes cascade with profile');
END
$$;

ROLLBACK;
SELECT 'behavior checks passed' AS result;
