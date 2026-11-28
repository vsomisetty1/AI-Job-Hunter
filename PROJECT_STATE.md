# Project state

Snapshot of the repository as of **2026-11-28**, at the Phase 10 commit `feat: hardening and release readiness` (version **0.10.0**).
It was written from the code, schema, tests and git history, not from memory.
Update it at the end of every phase.

Companion documents:
- [AI_CONTEXT.md](AI_CONTEXT.md): objectives, conventions, strategy
- [docs/architecture/](docs/architecture/): ADRs 001–016
- [RELEASE_READINESS.md](RELEASE_READINESS.md): what is verified, known gaps, gates to 1.0
- [DEPLOYMENT.md](DEPLOYMENT.md) and [BACKUP_AND_RECOVERY.md](BACKUP_AND_RECOVERY.md)
- [docs/MVP_VALIDATION.md](docs/MVP_VALIDATION.md): real-resume, real-job validation before automation
- [docs/AUTOMATION_VALIDATION.md](docs/AUTOMATION_VALIDATION.md): application automation on live forms (review mode)
- [docs/TESTING.md](docs/TESTING.md): CI and test layout
- [docs/VALIDATION.md](docs/VALIDATION.md): the real-world discovery check

## 1. Completed phases

| Phase | Commit(s) | Delivered |
|---|---|---|
| 1. Scaffold | `d1c3195` | Folder structure, placeholders (`PLACEHOLDER - implemented in PHASE N`), config files |
| 2. Database | `6b1b5ba`, `ea2f6c6` | PostgreSQL schema (14 tables), ORM models, Alembic migration 0001, schema/ORM consistency tests |
| 3. Backend foundation | `80f2ec3`, `1cb267f`, `f5a9cc9` | Config, logging, errors, async DB, single-user auth, middleware, scheduler, background tasks, settings/system/health APIs, CI workflow, toolchain upgrade |
| 4. Resume intelligence | `37e8196` | Upload validation and sandboxed extraction, deterministic parser, optional Claude enrichment, profile generation, resume versioning, frontend resume/profile pages |
| Audit | `96f8e92` | Production-readiness fixes: strict mypy, architecture tests, recovery of interrupted work, DB audit |
| 5. Job discovery | `e505d36` | Greenhouse/Lever/Ashby connectors, normalization, deduplication, persistence, discovery runs and monitoring, scheduler, Jobs and Discovery UI, real-world validation script |
| 6. Filtering and scoring | `5edc75b` | Migration 0004, cross-board duplicate sweep, Agent 4 rule filter, Agent 5 rule-based scoring, optional Claude scoring (cached, capped, paced), Discovery → Deduplication → Filtering → Scoring pipeline, scoring API, Jobs score column/filters/detail breakdown, Settings page |
| 7. Application packages | `3624669` | Migration 0005; Agent 6 tailoring with change log; Agent 7 PDF/DOCX rendering; Agent 8 cover letters; Agent 9 answers; truthfulness guard; package generation (background) and approval workflow (review, approve, reject, regenerate, mark submitted); packages API; approval queue, review, tailored resume, diff, cover letter and answers pages |
| MVP validation | `a0086bf` | Real resume + 5.4k real jobs: parsing fixes (DOCX tables, dates, locations, degrees, certifications, arrangement qualifiers, taxonomy), relevance-ranked tailoring/letters/answers (`agents/relevance.py`), honest skill claims, scoring calibration (`rules-3`) and 3× faster scoring, data lifecycle (package delete, retention, orphan sweep, storage report; ADR-013), empty-board note, expired jobs cannot be approved, `scripts/validate_mvp.py` |
| 8. Application automation (approval mode) | `a4703db` | Migration 0006 (submissions, automation logs; approval mode and user confirmation enforced in the database); universal form engine (fields by labels/ARIA/legends/nearby text, every control type, read-back); semantic field matcher; Playwright browser manager (one Chromium, context per run, cookies per platform, live review sessions with cap and idle timeout); Greenhouse/Lever/Ashby adapters; Agent 10 (upload, fill, validate, screenshot, stop for review; edit; confirmed submit); checkpoints and failure recovery; automation API; Applications queue, review, history, logs and recovery UI; mock-ATS browser tests; real-world review-mode validation (`scripts/validate_automation.py`) |
| 9. Learning and insights | `ecb5f32` | Migration 0007 (interview events, outcome milestones, withdrawn status, company industry, learning snapshots, recommendation states); outcome tracking with derived milestones and timeline; learning dataset, statistics (Wilson, Fisher + Holm, AUC + Mann-Whitney), metrics (funnel, rates, score accuracy, skill correlations, company/board/resume/package-style analytics), insights engine with statistical gates, recommendations, Learning Agent with daily snapshots; applications and insights APIs; Analytics dashboard, Interview pipeline, Outcome timeline, Company insights, Resume performance, Job boards, Recommendations pages |

| 10. Hardening and release readiness | `feat: hardening and release readiness` | Local request guard (Host allowlist, cross-site write refusal, security headers; ADR-016); approval mode only in the API and the database (migration 0008); generated API contract with backend, typecheck and runtime checks, and backend schemas tightened to match; Docker images and full Compose stack (loopback only, non-root, health checks); backup and restore scripts with round-trip tests; agent activity API and page; `package_service` and `automation_service` split; placeholders removed; Supabase bucket accepts screenshots; one version (0.10.0); RELEASE_READINESS, DEPLOYMENT, BACKUP_AND_RECOVERY, SUPABASE_SETUP |

**Not started:** see §13. Autonomous mode is deliberately not built and is blocked in the
database until a new ADR enables it.

## 2. Current architecture

A modular monolith: one FastAPI process (one worker) with an in-process scheduler, a Next.js frontend and one PostgreSQL database. Runs natively (`scripts/dev.sh`) or as three Compose services (`db`, `backend`, `frontend`), every port on 127.0.0.1 (DEPLOYMENT.md).

```
Next.js 16 (React 19, SWR)  ──HTTP /api/v1──►  FastAPI (python -m app, 127.0.0.1:8000)
                                                 ├─ routers → services → agents → repositories → models
                                                 ├─ adapters: connectors, documents, parsing, llm, storage
                                                 ├─ APScheduler (discovery every 6 h, maintenance daily)
                                                 └─ BackgroundTaskManager (resume processing, discovery runs)
                                                        │
                       PostgreSQL 19 (16+ works) ◄──────┘     Claude API (optional)
                       local disk or Supabase Storage          Greenhouse / Lever / Ashby public APIs
```

Backend layers are enforced by `backend/tests/unit/test_architecture.py`: imports only point down, there are no package cycles, and every module imports on its own.

| Layer | Packages |
|---|---|
| 8 composition root | `main.py`, `bootstrap.py`, `__main__.py` |
| 7 HTTP | `routers/`, `dependencies.py` |
| 6 jobs | `scheduler/` |
| 5 business logic | `services/`, `learning/` |
| 4 workers | `agents/` |
| 3 queries | `repositories/` |
| 2 adapters | `connectors/`, `documents/`, `parsing/`, `llm/`, `storage/`, `automation/` |
| 1 foundation | `core/` |
| 0 data | `models/`, `schemas/`, `utils/` |

Key rules:
- Every request passes the local request guard first: Host allowlist, cross-site writes refused (ADR-016).
- One request is one transaction (`get_db`).
- Repositories never commit.
- Background work opens its own short transactions and never holds one open during a network or Claude call.

## 3. Current capabilities (working today)

- **Resumes:**
  - Upload PDF/DOCX, which is validated, scanned (optionally), extracted in a sandbox and parsed deterministically.
  - Optional Claude enrichment of weak sections.
  - Edit parsed data (versioned); reparse; mark primary; download; delete.
- **Profile:**
  - Generated from the primary resume: years of experience, seniority, history, skills, education.
  - With Claude: target roles, transferable roles, industries, career analysis.
  - Editable; your edits survive regeneration.
- **Job discovery:**
  - Track company boards on Greenhouse, Lever or Ashby (23 suggestions built in).
  - Run discovery manually or on a schedule (incremental).
  - Search, filter and inspect jobs, including the raw board payload.
- **Filtering and scoring:**
  - Every discovery run continues into deduplication, the rule filter and scoring.
  - Rule filter: duplicates, excluded companies/keywords, locations, workplace, employment type, salary floor, sponsorship. Each job stores every rule's outcome.
  - Rule-based score 0–100 from skills, title relevance, seniority, location and salary, with matched/missing skills and a per-component breakdown.
  - Optional Claude score for the best matches (opt-in, API key, per-run/daily caps, pacing, cache).
  - Jobs page sorted by score with match/filtered/min-score controls and a Re-score button; job page explains score and filter decisions.
  - Settings or profile edits re-filter and re-score in the background.
- **Application packages:**
  - From a job page, generate a package: a resume tailored to the job (reordered, respelled, optionally reworded by Claude; never with added skills, employers, dates or numbers), a cover letter (150–300 words, from resume facts), and answers to common questions (why this company, why qualified, salary, relocation, sponsorship, work authorization, years and per-skill experience), each with its evidence.
  - PDF and DOCX of the tailored and the original resume and of the letter (ATS-friendly).
  - Review every change with its reason, edit answers, then approve (the application becomes `ready` in approval mode), reject, regenerate (new version) or record that you applied.
- **Application automation (approval mode):**
  - Applications page: approved packages ready to fill, open forms waiting for review, failed runs with recovery actions.
  - "Fill application form" opens the real Greenhouse/Lever/Ashby form in Chromium, uploads the tailored resume and cover letter, fills every field a fact supports, validates, screenshots and stops.
  - Review screen: resume/cover letter status, answers inserted with their source, missing fields (answer them inline: the open form changes), the form's validation messages, fields left for you (consent, self-identification, unknowns), screenshots. Retry, cancel, or submit with an explicit confirmation.
  - Submission history and structured automation logs; application, package and job statuses follow a confirmed submission.
- **Learning and insights:**
  - Interview pipeline: record a recruiter response, screens and interview rounds (scheduled/completed/cancelled/no-show), offers, rejections and withdrawals; status and milestones follow; full outcome timeline.
  - Dashboard: response/interview/offer rates with 95 % intervals, conversion funnel, score accuracy, skill correlations, results by job family and workplace, trend from Learning Agent snapshots.
  - Company, job board and resume/package-style analytics; set company industries for industry comparisons.
  - Insights only when the data supports them (minimum group sizes, Fisher exact + Holm, minimum effect); recommendations with their numbers and a link to act; dismiss or mark done.
- **Monitoring:**
  - Discovery runs with counts and per-company results.
  - Per-company crawl status and failure counts.
  - Connector health with a live probe.
  - `agent_runs` with tokens and cost.
  - Background task status; scheduled jobs list; `/health` and `/health/ready`.
- **Settings:** single-row preferences, edited on the Settings page or via `GET/PATCH /api/v1/settings`. Autonomous-mode fields are refused (ADR-016).
- **Agent activity:** `/activity` lists every agent run and pipeline stage with status, duration, tokens, cost and errors, filterable by agent and status, plus per-agent totals over a period (`/api/v1/agent-runs`, `/summary`, `/agents`).
- **Operations:** Docker images and Compose stack; `scripts/backup.sh` / `restore.sh` (verified checksums, schema-revision check, safety backup).

Verified live on 2026-11-27: 7 real boards, 1,697 jobs stored. A repeat run inserted 0 jobs and reported everything unchanged.

## 4. Database summary

PostgreSQL 15+ (CI uses 19). The schema is at Alembic head **0008**. `backend/schema.sql` is the readable reference. Migrations execute frozen SQL files (`backend/migrations/sql/`) pinned by SHA-256 in `tests/unit/test_schema_sql.py`.

| Table | Purpose | Used by |
|---|---|---|
| `candidate_profiles` | Parsed and inferred career profile, user overrides, inference status | Phase 4 |
| `resumes` | Uploaded files (hash, storage key, parse status, primary flag) | Phase 4 |
| `resume_versions` | `original` / `parsed` / `tailored` versions; tailored ones keep `base_version_id`, `changes` (section, before/after, reason, time) and `tailoring` notes; rendered `pdf_path`/`docx_path` | Phases 4, 7 |
| `companies` | Tracked job boards (source + slug), crawl status, failures | Phase 5 |
| `jobs` | Normalized postings: dedup key, content hash, first/last seen, expiry, raw payload; filter decision (`filter_result`, `filter_reason`, `filter_hash`, `filtered_at`) and `duplicate_of` | Phases 5–6 |
| `discovery_runs` | One row per discovery run; at most one `running` (partial unique index) | Phase 5 |
| `agent_runs` | One row per agent invocation or pipeline stage: status, timing, tokens, USD cost | Phases 4–6 |
| `llm_cache_entries` | Claude response cache, keyed by prompt version, model and input | Phase 4 |
| `settings` | Single-row preferences (locations, remote, job types, salary, sponsorship, work authorization, `willing_to_relocate`, exclusions, mode, cap, `discovery_enabled`, `claude_scoring_enabled`, `claude_scoring_min_score`) | Phases 3, 6, 7 |
| `job_scores` | One current score per job + profile + `scoring_method` (`rules`/`claude`): components, breakdown, matched/missing skills, input hash | Phase 6 |
| `application_packages` | One per generation: job, profile, version, status (generating → generated → reviewed → approved → submitted; rejected/failed/superseded), links to score, base and tailored resume version, cover letter and application; score snapshot; lifecycle timestamps; one live package per job | Phase 7 |
| `cover_letters` | Every generated letter (version per job + profile), word count, method (`rules`/`claude`), facts and notes | Phase 7 |
| `application_answers` | Answers owned by a package (or later an application) with source, confidence, `needs_review` and evidence | Phase 7 |
| `applications`, `application_events` | Created/updated on approval (`ready`, APPROVAL_MODE) with the package's artifacts; `automation_state` follows runs; events for created/approved/automation_started/needs_manual/retry/failed/submitted | Phases 7–8 |
| `application_submissions` | One automation run: platform, apply URL, mode (APPROVAL_MODE only), status (queued → in_progress → waiting_for_review → submitting → submitted; failed/cancelled), step, checkpoint, review report, user edits, screenshots, attempts, error kind, `confirmed_at` (required before submitting), timestamps; one active run per application | Phase 8 |
| `automation_logs` | Append-only structured log lines per run (level, step, message, detail) | Phase 8 |
| `browser_sessions` | Playwright storage state (cookies) per platform, saved after each run | Phase 8 |
| `interview_events` | Recorded outcomes per application: stage (recruiter response … final round, offer, rejection, withdrawal), status (scheduled/completed/cancelled/no_show), date, notes; `applications` gains derived `responded_at`, `first_interview_at`, `offer_at`, `rejected_at`, `withdrawn_at` and a `withdrawn` status | Phase 9 |
| `learning_snapshots` | Append-only Learning Agent output (summary, insights, recommendations) keyed by an input hash | Phase 9 |
| `recommendation_states` | Recommendations you dismissed or did | Phase 9 |
| `companies.industry` | Set by you, never inferred (analytics) | Phase 9 |
| `settings.application_mode`, `applications.application_mode` | Limited to `APPROVAL_MODE` (0008); `auto_apply_threshold` and `daily_application_cap` kept, unused and not editable | Phase 10 |

Conventions:
- uuid primary keys; `timestamptz`.
- Enums are `text` + CHECK.
- Named constraints: `ck_`, `uq_`, `fk_`, `ix_`, `trg_`.
- `updated_at` triggers.
- Jobs cannot be deleted while applications exist.

`tests/sql/` checks the migrated catalog against `schema.sql` and checks constraint behaviour.

## 5. Backend summary

Stack:
- Python 3.14, FastAPI 0.165, Pydantic 2.14, SQLAlchemy 2.1 (async; asyncpg)
- Alembic, APScheduler 3.11, httpx 0.28, anthropic SDK
- ruff, mypy `--strict`, pytest 9, respx

| Area | Implemented | Placeholder |
|---|---|---|
| Routers (`/api/v1`) | `resumes`, `profile`, `settings`, `system`, `jobs`, `companies`, `discovery`, `scoring`, `packages`, `automation`, `applications`, `insights`, `agent-runs`; unversioned `health` | — |
| Services | resume, resume_processing, profile, settings, pipeline (`JobPipeline`), job, company, discovery, filtering, scoring, packages (`package_generator.PackageGenerator`, `package_workflow.PackageWorkflow`, `package_inputs`), lifecycle, automation (`automation_service.AutomationService`, `automation_facts`, `automation_recorder.DbRecorder`, `automation_views`), outcome (`OutcomeService`), job_normalizer; `learning/` (dataset, stats, families, metrics, insights, recommendations, `LearningAgent`, `LearningService`) | — |
| Agents | 0 resume parser, 1 profile inference, 2 job discovery, 3 deduplication, 4 rule filtering, 5 rule-based scoring, 6 resume tailoring, 7 PDF/DOCX rendering, 8 cover letters, 9 application answers, 10 application automation; `truthfulness.py`; `relevance.py`; `runs.py` (agent_runs) | — |
| Adapters | connectors (3 platforms), documents, parsing, llm (client, cache, pricing, rate limiter; prompts for parse/profile/skills/career/job scoring/tailoring/cover letter/answers), storage (local, Supabase), automation (browser manager, DOM extraction, form engine, field matcher, checkpoints, recovery, Greenhouse/Lever/Ashby adapters) | — |

Behaviour:
- **Errors:** every error is returned as `{"error": {"code", "message", "details"}}` and carries an `X-Request-ID`.
- **Startup:** work left `running` by a crashed process is marked failed or cancelled.
- **Maintenance:** a daily job prunes the expired Claude cache, plus `agent_runs` and `discovery_runs` older than 180 days.

## 6. Frontend summary

Stack: Next.js 16.4 (App Router), React 19.3, TypeScript 6.0, Tailwind 4, SWR 2.5, Vitest 5 with Testing Library, ESLint 9.

| Route | State |
|---|---|
| `/resumes`, `/resumes/[id]` | Done: upload, list, actions, parsed-data editor, version history |
| `/profile` | Done: view, edit, regenerate |
| `/jobs`, `/jobs/[id]` | Done: search, filters (incl. matches/filtered, min score), sort by score, pagination, re-score; detail with score breakdown, filter checks, raw JSON |
| `/settings` | Done: locations, workplace, employment types, salary, sponsorship, exclusions, Claude scoring |
| `/discovery` | Done: run and follow discovery, connector health, companies, suggestions, run history |
| `/packages` | Done: approval queue (needs review / approved / submitted / rejected & failed / all) |
| `/applications` | Done: queue (ready to fill, in progress / waiting for review, needs attention with failure recovery) |
| `/applications/[id]` | Done: application review (progress, checklist, missing fields with inline answers, validation problems, answers inserted, left for you, screenshots, retry / cancel / confirmed submit) |
| `/applications/history`, `/applications/logs` | Done: submission history (status filter, timestamps, errors); automation logs (level filter, per run) |
| `/packages/[id]` (+ `/resume`, `/diff`, `/cover-letter`, `/answers`) | Done: package review with approve/reject/regenerate/“I applied”, tailored resume viewer, resume diff viewer, cover letter viewer, answers viewer with editing; downloads |
| `/` and `/insights` | Done: analytics dashboard (rates with intervals, funnel, insights, score accuracy, job families, skills, workplace, trend; run the Learning Agent) |
| `/insights/pipeline`, `/insights/timeline` | Done: interview pipeline (stage columns, record / update / delete events), outcome timeline |
| `/insights/companies`, `/insights/resumes`, `/insights/boards`, `/insights/recommendations` | Done: company insights (with industry), resume performance, job board performance, recommendations (dismiss / done / restore) and all insights |
| `/activity` | Done: agent activity (per-agent totals over a period, runs filtered by agent and status, paginated) |

The API client lives in `src/lib/api/`, hooks in `src/hooks/`, and types mirroring the backend schemas in `src/types/index.ts`, checked against the generated `src/types/api.gen.ts` by `contract.ts` (typecheck) and `contract.test.ts` (every call is a backend operation).
- Links are rendered only for http(s) URLs (`safeUrl`).
- Job text is rendered as text, never as HTML.

## 7. Resume intelligence summary (Phase 4)

The pipeline, in order:
1. **Validation** (`documents/validation.py`): magic-byte type check, size and page limits, rejection of active content (PDF JS/launch/embedded/XFA, DOCX macros/ActiveX/OLE/remote templates, zip bombs).
2. **Optional ClamAV scan** (fails closed).
3. **Sandboxed extraction** (`documents/sandbox.py`): a child process with memory and CPU limits, killed on timeout.
4. **Deterministic parsing** (`parsing/`): sections, contact, experience, education, skills (aliases), certifications, projects, publications, awards, plus a per-section confidence score.
5. **Claude enrichment (Agent 0):** only when configured and sections are weak; only those sections' text is sent; at most one call.
6. **Profile (Agent 1):** deterministic first. With Claude it adds profile inference, career analysis and skill extraction, from a PII-free JSON (no name, contact details or links).
7. **Versioning:** each edit is a new `parsed` version; `tailored` is reserved for Phase 6/7.

Processing runs in the background (`services/resume_processing.py`), and profile builds are serialized.

## 8. Job discovery summary (Phase 5)

| Piece | What it does |
|---|---|
| Connectors (`connectors/`) | One interface (`discover_jobs`, `normalize_job`, `validate_job`, `health_check`) and a shared `HttpFetcher` (timeouts, 50 MB cap, retries with jitter for timeouts/429/5xx honouring Retry-After; 404 never retried). Greenhouse: single response, pay ranges, incompleteness detected from `meta.total`. Lever: skip/limit pagination, US then EU region. Ashby: single response, unlisted postings skipped, structured compensation. |
| Normalization | `connectors/normalize.py`: HTML → plain text, requirements from requirement/qualification sections, remote type, employment type, yearly salary (structured first, then text), dates |
| Validation | Invalid postings (missing title, non-http(s) URL, ...) are counted and sampled, never stored |
| Deduplication | `agents/agent_3_deduplication.py`. In order: (1) same company + board job id → update if the content hash changed, else mark seen; (2) URL owned by another job → skip; (3) company + title + location fingerprint owned by another company row → skip (cross-platform duplicate) |
| Persistence | One short transaction per company. `first_seen_at` never changes and `last_seen_at` advances. Missing jobs are expired only when the response is complete, and never if `applied`. Reappearing jobs are revived. |
| Runs | `services/discovery_service.py`: concurrent crawls (`DISCOVERY_CONCURRENCY`), per-company failure isolation, counts stored in `discovery_runs`, company crawl status and failure counters, one run at a time (409) |
| Scheduling | Every `DISCOVERY_INTERVAL_MINUTES` (360); incremental, so only companies not crawled within 90 % of the interval run. It can be switched off with `settings.discovery_enabled`. |
| API | `GET /jobs` (+ `/stats`, `/{id}`, `/{id}/raw`); `/companies` (+ `/directory`, `/suggested`); `POST/GET /discovery/runs`; `GET /discovery/health?probe=` |

Validation:
- `scripts/validate_discovery.sh` runs the end-to-end check against live boards.
- `tests/live/` holds opt-in connector tests, also run by a weekly workflow.

## 8b. Filtering and scoring summary (Phase 6)

See ADR-011 and the README section. Pipeline: `JobPipeline` (`services/pipeline_service.py`) runs Discovery → Deduplication (`FilteringService.mark_duplicates`) → Filtering (Agent 4 via `FilteringService.run`) → Scoring (Agent 5 + optional Claude via `ScoringService.run`), each stage an `agent_runs` row, serialised by a lock. Filter decisions and rule scores are skipped when their input hash is unchanged. A Claude score is the effective score only while its `input_hash` equals the rule row's. Claude limits: `CLAUDE_SCORING_MAX_PER_RUN`, `CLAUDE_SCORING_MAX_PER_DAY` (counted from `agent_runs`), `CLAUDE_SCORING_PER_MINUTE`.

## 8c. Application packages summary (Phase 7)

See ADR-012 and the README section. `PackageGenerator.generate` (`services/package_generator.py`, background task) loads the job, active profile, primary resume's latest parsed version, settings and the job's effective score (computed with Agent 5 if the job was never scored), then runs Agents 6, 8 and 9 with no transaction open, renders files with Agent 7, writes them to storage, and saves the tailored resume version, cover letter, answers and package in one short transaction. `PackageWorkflow` (`services/package_workflow.py`) handles the state changes inside the request. `app/agents/truthfulness.py` checks every generated text: no skill or number the resume lacks; tailored resumes keep contact, roles, dates, education and certifications identical.

## 8d. MVP validation summary

See [docs/MVP_VALIDATION.md](docs/MVP_VALIDATION.md) (anonymised; the full report is personal
and stays in the git-ignored `validation-output/`). Final run on the real resume: parse
confidence 1.0 with no lost lines; 10 packages for 10 companies with 0 harness issues; cover
letter 4-gram overlap mean 0.30 (was 0.34, max 0.51 from 0.75); resume renders on 2 pages.
Lifecycle: `LifecycleService` (`services/lifecycle_service.py`) runs in the daily maintenance
job; `DELETE /packages/{id}`, `GET /system/storage`, `POST /system/storage/cleanup`;
settings `PACKAGE_RETENTION_DAYS` (90) and `ORPHAN_GRACE_HOURS` (24).

## 8e. Application automation summary (Phase 8)

See ADR-014, the README section and [docs/AUTOMATION_VALIDATION.md](docs/AUTOMATION_VALIDATION.md).
`AutomationService` (`services/automation_service.py`) starts a run for an approved package
(`application_submissions` row, background task), builds applicant facts from the approved
package only (`services/automation_facts.py`: tailored resume, profile, settings, package
answers usable only if reviewed), and calls Agent 10 (`agents/agent_10_application_agent.py`)
with a `DbRecorder` (`services/automation_recorder.py`) for logs, checkpoints and screenshots;
`services/automation_views.py` turns submission rows into API responses. Agent 10 uses `automation/`: `BrowserManager` and
`SessionRegistry` (browser lifecycle, live review sessions), `dom.py` (in-page extraction),
`form_engine.py` (fill, upload, validate), `field_matcher.py` (concepts and option choice),
`checkpoints.py`, `recovery.py` (error kinds, retries) and `platforms/` (adapters). Submits
happen only via `confirm_submit` + `finish_submit`. Startup marks interrupted runs failed;
a 5-minute job closes idle forms; the daily maintenance prunes old automation logs.
Settings: `AUTOMATION_ENABLED`, `AUTOMATION_HEADLESS`, `AUTOMATION_BROWSER_PATH`,
`AUTOMATION_MAX_SESSIONS` (2), `AUTOMATION_SESSION_IDLE_MINUTES` (30),
`AUTOMATION_MAX_ATTEMPTS` (2), timeouts.

## 8f. Learning and insights summary (Phase 9)

See ADR-015 and the README section. `OutcomeService` (`services/outcome_service.py`) records
interview events and derives the application's milestones and status (`derive`, pure).
`app/learning/`: `dataset.py` builds one record per job with a package from your rows;
`stats.py` (Wilson, Fisher exact, Holm, AUC and its Mann-Whitney p-value); `metrics.py`
(funnel, overview, score accuracy, skill correlations, segments and dimensions);
`insights.py` (statistically gated statements); `recommendations.py`; `agent.py`
(`LearningAgent`, daily via the scheduler and on demand, `agent_runs` row, snapshot only
when the input hash changed); `service.py` (`LearningService` for the API, computed live).
Thresholds: 10 submitted applications before comparisons, 5 per group, p <= 0.10 after Holm,
10 points and 1.5x minimum effect; score verdicts need a 10-point score spread and
p <= 0.10.

## 8g. Hardening summary (Phase 10)

See ADR-016, DEPLOYMENT.md and BACKUP_AND_RECOVERY.md.
- `core/middleware.LocalRequestGuardMiddleware`: `ALLOWED_HOSTS` (400 `host_not_allowed`),
  cross-site writes (403 `cross_site_request`), security headers; `CONTAINER_LOOPBACK_ONLY`
  lets the image bind 0.0.0.0 inside its container with `AUTH_MODE=none`.
- Settings API refuses the autonomous-mode fields; migration 0008 pins `application_mode`.
- `scripts/gen_api_contract.py` -> `frontend/src/types/api.gen.ts`; checked by
  `tests/unit/test_api_contract.py`, `src/types/contract.ts`, `src/types/contract.test.ts`.
- `backend/Dockerfile`, `frontend/Dockerfile`, `docker-compose.yml`, `scripts/smoke_compose.sh`.
- `scripts/backup.sh`, `scripts/restore.sh`, `scripts/lib/common.sh`,
  `scripts/test_backup_restore.sh`.
- `LOCAL_STORAGE_DIR` relative paths now resolve against `backend/` (`Settings.local_storage_path`),
  whatever the working directory.

## 9. Testing status

- **Backend:** 654 tests pass (unit, integration on real Postgres 19, and browser
  tests driving real Chromium against mock Greenhouse/Lever/Ashby pages); 3 live tests are
  deselected by default. CI fails on any skip; warnings are errors.
- **Frontend:** 150 Vitest tests, including the API contract test (every API call
  is a backend operation); `npm run typecheck` includes the compile-time contract.
- **CI** (`.github/workflows/ci.yml`, every push and pull request):
  - backend: pip check, Chromium, ruff (incl. bandit rules), pip-audit, format, API contract
    current, mypy strict, pytest on Postgres 19, smoke script against the real server,
    backup/restore round trip on the smoke test's data
  - frontend: npm audit, typecheck (incl. contract), lint, tests, build
  - scripts: shellcheck
  - docker: Compose config, build both images (backend with Chromium), start the stack,
    `scripts/smoke_compose.sh` (readiness, security headers, loopback-only ports, non-root
    users, request guard, approval-mode-only settings, Chromium fills a form in the image,
    backup and restore of the Compose volumes)
- **Weekly:** `live-connectors.yml` (real Greenhouse/Lever/Ashby APIs).
- **Manual, real world:** `scripts/validate_discovery.sh`, `scripts/validate_mvp.py`,
  `scripts/validate_automation.py` (review mode only).
- **Not covered by automated tests:** a real submission on a live ATS (never done: Phase 11);
  the browser running the frontend against the real backend (Phase 12); untyped analytics
  responses (`/insights/summary`, `/companies`, `/boards`, `/resumes`) in the contract.

## 10. Technical debt

- Analytics endpoints (`/insights/summary`, `/insights/companies`, `/insights/boards`,
  `/insights/resumes`) return untyped dictionaries, so the API contract cannot check them;
  give them response models.
- `SubmissionDetail.review` and `.checkpoint`, and `agent_runs` input/output summaries, are
  free-form JSON in the API.
- Analytics are computed live on each request from all rows: fine for hundreds of
  applications; cache or use snapshots if it ever grows to many thousands.
- An open review form lives in process memory: a restart or the idle timeout closes it, and
  the user retries (the checkpoint and saved edits make that quick).
- Platform adapters encode observed behaviour (Greenhouse embed URL, Lever resume parsing and
  location suggestions); a platform redesign may need an adapter update. The engine itself is
  selector-free.
- Reparsing a resume does not rebuild the profile or rescore jobs automatically (each is one
  action).
- The orphan sweep lists every stored file and referenced path: fine for a personal store,
  not for a very large one.
- Background tasks (package generation, discovery, automation runs) are lost on restart and
  marked failed/cancelled at the next start.
- Agent 5's skill matching knows the built-in taxonomy plus the candidate's own skills only;
  synonyms need Claude. Unknown skills are scored neutral.
- The Claude daily cap counts calls recorded by scoring stages in `agent_runs`; a scoring
  path outside the pipeline would not be counted.
- Job search uses `ILIKE` per word with no full-text index (fine for thousands of rows).
- The suggested-company directory (`connectors/company_directory.py`) is static (verified
  2026-11-27) and will drift.
- `llm/pricing.py` holds a manual price table.
- Toolchain holdbacks (`docs/TESTING.md`): `httpx` 0.28 (supabase), ESLint 9 and
  TypeScript 6 (`eslint-config-next`).
- The real-world validation scripts (`scripts/validate_*.py`) are not linted in CI.
- The Compose frontend bakes the API URL into its bundle at build time (changing
  `BACKEND_PORT` needs a frontend rebuild).

Resolved in Phase 10: placeholder modules and pages, the unconfigurable-but-accepted
autonomous mode, Docker placeholders, `docs/SETUP.md`/`ARCHITECTURE.md` placeholders,
hand-copied types without checks, the two oversized services, the unbumped version, the
Supabase bucket rejecting screenshots, and unused `PLAYWRIGHT_HEADLESS`/`BROWSER_STATE_DIR`
settings.

## 11. Known limitations

- **Single process:** background tasks are in memory; the scheduler needs exactly one worker.
- **Local only:** no real auth (`AUTH_MODE=none` on loopback; `api_key` exists but the
  frontend cannot send it). Not built for LAN or public deployment.
- **Automation:** approval mode only. Never submitted on a live ATS yet. CAPTCHAs need a
  visible browser (native backend, `AUTOMATION_HEADLESS=false`); the Compose image is
  headless only. Location autocompletes depend on the platforms' third-party lookups.
  Attaching a file uploads it to the ATS before submit (Greenhouse, Ashby). Checkbox groups
  and education "School" lists with no exact match are left for the user. Only Greenhouse,
  Lever and Ashby.
- **Greenhouse:** if the API ever truncated a board without reporting it in `meta.total`,
  the run would not notice; expiry would be wrong only for that crawl.
- **Salary:** yearly only.
- **Fingerprint dedup includes location:** the same role with differently written locations
  on two platforms is kept twice.
- **Requirement extraction is heuristic** (headings): about 90–100 % coverage on sampled boards.
- **Only boards you add** (no search across all companies). Location matching knows a small
  alias table and US states only. Sponsorship detection is phrase-based.
- Cover letters and the "why this company" answer are templates over facts unless Claude is
  used; they are flagged for personalisation. Per-skill years can over-count partial use
  (answers say "about" and are flagged).
- **Learning:** outcomes are only as complete as what you record; insights are correlations;
  fewer than 10 submitted applications shows facts only.
- **Backups:** Supabase storage and Supabase Postgres restores are not covered by the scripts.

## 12. Deferred functionality

| Item | Where it goes |
|---|---|
| Real applications in approval mode, outcome recording, fixes from real use | Phase 11 |
| Frontend-through-backend Playwright tests on the Compose stack | Phase 12 |
| Claude Code commands for shortlist scoring, tailoring and letters under the Pro plan (via the API) | Phase 13 |
| Response models for the analytics endpoints (contract coverage) | Phase 12 |
| Autonomous mode | After 1.0, only with evidence from Phase 11 and a new ADR superseding ADR-014/016 |
| Workday connector | After 1.0 (ADR-008) |
| Full-text job search, self-updating company directory | After 1.0 |

## 13. Roadmap to 1.0

This is the single roadmap; README and AI_CONTEXT point here.

| Step | Scope | Exit criterion |
|---|---|---|
| 10. Hardening and release readiness | ADR-016 (done) | CI green including the Docker job; RELEASE_READINESS.md written |
| 11. Real-use validation | Use the app for real in approval mode: track boards, generate and review packages, fill and **submit** real applications with confirmation, record every reply and interview. Fix what breaks (submit confirmation, CAPTCHA on submit, adapters). Document like AUTOMATION_VALIDATION.md. | At least 10 real confirmed submissions with no wrong or duplicate submission; first statistically gated insights appear |
| 12. End-to-end tests | Playwright through the frontend against the Compose stack (mock ATS pages, no network); response models for the analytics endpoints | E2E job green in CI on every push |
| 13. Claude Code command path | `.claude/commands/` for shortlist scoring, tailoring and cover letters through the API, under the owner's Pro plan; never OAuth inside the app (ADR-006) | Commands round-trip through the API; API-side tests |
| **1.0** | RELEASE_READINESS.md gates all met; version 1.0.0; changelog; tag | Tagged release |

After 1.0 (each needs its own decision): autonomous mode (only if Phase 11's data shows
what converts; new ADR; migration relaxing the 0006/0008 constraints; threshold, daily cap,
kill switch), Workday discovery, more providers, full-text search, multi-user mode.
