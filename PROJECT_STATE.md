# Project state

Snapshot of the repository as of **2026-11-27**, at commit `e505d36 feat: job discovery engine`.
It was written from the code, schema, tests and git history, not from memory.
Update it at the end of every phase.

Companion documents:
- [AI_CONTEXT.md](AI_CONTEXT.md): objectives, conventions, strategy
- [docs/architecture/](docs/architecture/): ADRs 001–010
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

**Not started:** Phase 6 (rule filtering, scoring, learning), Phase 7 (application packages and automation), Phase 8 (remaining frontend), Phase 9 (deployment), Phase 10 (end-to-end testing).

## 2. Current architecture

A modular monolith: one FastAPI process (one worker) with an in-process scheduler, a Next.js frontend and one PostgreSQL database.

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
- **Monitoring:**
  - Discovery runs with counts and per-company results.
  - Per-company crawl status and failure counts.
  - Connector health with a live probe.
  - `agent_runs` with tokens and cost.
  - Background task status; scheduled jobs list; `/health` and `/health/ready`.
- **Settings:** single-row preferences via API (`GET/PATCH /api/v1/settings`). There is no settings UI yet.

Verified live on 2026-11-27: 7 real boards, 1,697 jobs stored. A repeat run inserted 0 jobs and reported everything unchanged.

## 4. Database summary

PostgreSQL 15+ (CI uses 19). The schema is at Alembic head **0003**. `backend/schema.sql` is the readable reference. Migrations execute frozen SQL files (`backend/migrations/sql/`) pinned by SHA-256 in `tests/unit/test_schema_sql.py`.

| Table | Purpose | Used by |
|---|---|---|
| `candidate_profiles` | Parsed and inferred career profile, user overrides, inference status | Phase 4 |
| `resumes` | Uploaded files (hash, storage key, parse status, primary flag) | Phase 4 |
| `resume_versions` | `original` / `parsed` / `tailored` versions with history | Phase 4 (tailored: Phase 6/7) |
| `companies` | Tracked job boards (source + slug), crawl status, failures | Phase 5 |
| `jobs` | Normalized postings: dedup key, content hash, first/last seen, expiry, raw payload | Phase 5 |
| `discovery_runs` | One row per discovery run; at most one `running` (partial unique index) | Phase 5 |
| `agent_runs` | One row per agent invocation: status, timing, tokens, USD cost | Phases 4–5 |
| `llm_cache_entries` | Claude response cache, keyed by prompt version, model and input | Phase 4 |
| `settings` | Single-row preferences (locations, remote, salary, exclusions, mode, cap, `discovery_enabled`) | Phase 3 |
| `job_scores` | Scoring output | **unused**, Phase 6 |
| `cover_letters` | Generated letters | **unused**, Phase 7 |
| `applications`, `application_events`, `application_answers` | Application tracking and answers | **unused**, Phase 7 |
| `browser_sessions` | Playwright storage state per platform | **unused**, Phase 7 |

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
| Routers (`/api/v1`) | `resumes`, `profile`, `settings`, `system`, `jobs`, `companies`, `discovery`; unversioned `health` | `applications`, `insights`, `agent_runs` |
| Services | resume, resume_processing, profile, settings, pipeline, job, company, discovery, job_normalizer | scoring, application |
| Agents | 0 resume parser, 1 profile inference, 2 job discovery, 3 deduplication; `runs.py` (agent_runs) | 4 rule filtering, 5 scoring, 6 tailoring, 7 resume generation, 8 cover letters, 9 answers, 10 application agent |
| Adapters | connectors (3 platforms), documents, parsing, llm (client, cache, pricing; prompts for parse/profile/skills/career), storage (local, Supabase) | automation (Playwright), llm prompts for scoring/tailoring/cover letters/answers |

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
| `/jobs`, `/jobs/[id]` | Done: search, filters, sort, pagination, detail, raw JSON |
| `/discovery` | Done: run and follow discovery, connector health, companies, suggestions, run history |
| `/` (dashboard), `/applications`, `/activity`, `/settings` | Placeholder pages |

The API client lives in `src/lib/api/`, hooks in `src/hooks/`, and types mirroring the backend schemas in `src/types/index.ts`.
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

## 9. Testing status

- **Backend:**
  - 283 tests pass (unit, plus integration on real Postgres). The 3 live tests are deselected by default.
  - CI fails on any skip; warnings are errors.
- **Frontend:** 31 Vitest tests.
- **CI** (`.github/workflows/ci.yml`, on every push):
  - backend: pip check, ruff (incl. security rules), pip-audit, format, mypy strict, pytest on Postgres 19, smoke script against the real server
  - frontend: npm audit, typecheck, lint, test, build
- **Weekly:** `live-connectors.yml`.
- **Empty test placeholders:** `tests/unit/test_rule_filtering.py`, `test_scoring.py`, `test_form_engine.py`, `test_resume_parser.py`, `tests/integration/test_api.py`, `test_pipeline.py`, `tests/e2e/test_apply_flow.py`, `frontend/e2e/dashboard.spec.ts`. Playwright e2e is not run in CI.

## 10. Technical debt

- `Settings.app_version` is still `0.4.0` (not bumped for Phase 5).
- `docs/ARCHITECTURE.md`, `docs/SETUP.md` and `docs/SUPABASE_SETUP.md` are still Phase 1 placeholders. ADRs and this file now carry that content; `docs/PHASE_3_PLAN.md` is historical.
- `backend/Dockerfile` and `frontend/Dockerfile` are placeholders. `docker-compose.yml` runs only the database.
- `PipelineService` (stage runner) has no stages yet. Discovery runs through `DiscoveryService` directly, and scoring may plug in as stages or call services directly; this should be decided in Phase 6.
- Job search uses `ILIKE` per word with no full-text index. That is fine for thousands of rows; add `tsvector`/`pg_trgm` if it grows.
- The suggested-company directory (`connectors/company_directory.py`) is static, verified on 2026-11-27, and will drift.
- `llm/pricing.py` holds a manual price table.
- `httpx` is held at 0.28.1 by `supabase`; ESLint 9 and TypeScript 6 are held back by `eslint-config-next`/`typescript-eslint` (see `docs/TESTING.md`).
- Several placeholder modules for Phases 6–10 exist only as docstrings (listed in §5). Before relying on their names, confirm the design still fits.

## 11. Known limitations

- **Single process:**
  - Background tasks are in memory and lost on restart (the run is then marked cancelled).
  - The scheduler needs exactly one worker.
- **No real auth:** `AUTH_MODE=none` is allowed only on loopback; `api_key` mode exists for anything else. Not built for public deployment.
- **Greenhouse:** if the API ever truncated a board without reporting it in `meta.total`, the run would not notice. Expiry would still be wrong only for that one crawl.
- **Salary:** yearly only. Hourly and other rates are left in `compensation_text` without numbers.
- **Fingerprint dedup includes location:** the same role with differently written locations on two platforms is kept twice.
- **Requirement extraction is heuristic** (headings): coverage was about 90–100 % on the sampled live boards, and some postings have none.
- **Only three ATS platforms**, and only boards you add (no search across all companies).
- No settings, dashboard, applications or activity UI yet.

## 12. Deferred functionality

| Item | Where it goes |
|---|---|
| Agent 4 rule filtering (locations, remote preference, exclusions, job types) | Phase 6, before scoring |
| Agent 5 job scoring + `job_scores`; learning/insights | Phase 6 |
| Agents 6–9: resume tailoring, resume generation, cover letters, application answers | Phase 7 |
| Agent 10 + `automation/`: Playwright form filling, checkpoints, approval/autonomous modes, daily cap | Phase 7 |
| Settings, dashboard, applications, activity pages | Phase 8 |
| Dockerfiles, full compose, deploy docs, Supabase setup doc | Phase 9 |
| Playwright e2e in CI, pipeline/integration placeholders | Phase 10 (plus each phase's own tests) |
| Workday connector | After Phase 7; see ADR-008 |

## 13. Next recommended phases

1. **Phase 6: filtering and scoring.**
   - Implement Agent 4 as a deterministic filter over `jobs` with status `new` (settings: locations, remote, job types, excluded companies/keywords, salary floor), setting status `filtered` or passing the job through.
   - Then add deterministic scoring (skill overlap with the profile, seniority, salary, location) into `job_scores`.
   - Add an optional Claude scoring path for a shortlist only, plus Claude Code commands for scoring under the Pro plan (see AI_CONTEXT.md).
   - Add a scores column and filters to the Jobs UI, and the Settings page so the preferences are editable.
   - Extend CI as usual.
2. **Phase 7:** application packages (tailored resume version, cover letter, answers), then approval-mode automation for Greenhouse/Lever/Ashby forms.
3. **Phase 8:** dashboard, applications, activity pages.
4. **Phase 9:** containers and the deployment story (still personal use).
5. **Phase 10:** end-to-end tests.
