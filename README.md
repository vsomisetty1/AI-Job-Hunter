# AI Job Hunter

Autonomous job-search agent: parse a resume, discover jobs (Greenhouse, Lever, Ashby),
score them with Claude, tailor resumes, generate application packages, and apply
(approval or autonomous mode). Workday can be added later via the connector and
platform-adapter interfaces.

**Stack:** Next.js 16 + React 19 + TypeScript + Tailwind 4 (Node 26) · FastAPI on Python 3.14 · PostgreSQL 19 · Supabase Storage · Playwright · Claude API · Docker

**Start here:** [PROJECT_STATE.md](PROJECT_STATE.md) (what exists now),
[AI_CONTEXT.md](AI_CONTEXT.md) (objectives, conventions, AI strategy) and
[docs/architecture/](docs/architecture/) (ADR-001 to ADR-010).

CI runs lint, tests against Postgres 19, a real-server smoke test and the frontend build
on every push: see [docs/TESTING.md](docs/TESTING.md).

## Build status

| Phase | Scope | Status |
|---|---|---|
| 1 | Folder structure + project config | Done |
| 2 | Database (schema, migrations, ORM) | Done |
| 3 | Backend foundation | Done |
| 4 | Resume intelligence (Agents 0, 1; resume versioning) | Done |
| 5 | Job discovery (Agents 2, 3; Agent 4 filtering moves to Phase 6) | Done |
| 6 | Rule filtering + scoring (Agents 4, 5; optional Claude scoring; learning moves to Phase 8) | Done |
| 7 | Application packages + automation (Agents 6, 7, 8, 9, 10) | Pending |
| 8 | Frontend | Pending |
| 9 | Deployment | Pending |
| 10 | Testing | Pending |

Files containing `PLACEHOLDER - implemented in PHASE N` are stubs filled in by that phase.

## Resume intelligence (Phase 4)

Upload a PDF or DOCX on the **Resumes** page (or `POST /api/v1/resumes`). The flow:

1. **Validation** (`app/documents/validation.py`): size limit, type detected from the
   bytes (not the name), and rejection of active content: PDF JavaScript / launch
   actions / embedded files / forms, DOCX macros, ActiveX, embedded objects, remote
   templates, zip bombs. Optional ClamAV scan (`VIRUS_SCANNER=clamd`).
2. **Sandboxed extraction** (`app/documents/sandbox.py`): text is read in a separate
   process with memory/CPU limits that is killed on timeout; encrypted PDFs are refused.
3. **Deterministic parsing** (`app/parsing/`): sections, contact details, experience,
   education, skills (with alias normalisation), certifications, projects,
   publications, awards, plus a confidence score per section. No tokens used.
4. **Claude only when needed** (`app/agents/agent_0_resume_parser.py`): if sections are
   weak, only those sections' text is sent (the whole resume only for unrecognisable
   layouts), in the background after upload.
5. **Profile** (`app/agents/agent_1_profile_inference.py`): years of experience (overlaps
   merged), career history, seniority, education/certification summaries and skills
   are computed locally; Claude adds target roles, transferable roles, industries and a
   career analysis from a compact JSON **without name, contact details or links**.
6. **Versions**: every resume keeps `original` (the file), `parsed` (parser output and
   each of your edits) and `tailored` (per role/company/job) versions with history.

Edit parsed data on the resume page (saved as a new version), and edit the profile on
the **Profile** page: edited fields are remembered and survive "Regenerate" unless you
untick "Keep my edits".

**Claude usage.** Optional (`ANTHROPIC_API_KEY`). Structured outputs, server-side refusal
fallback, SDK retries with backoff, and a Postgres cache keyed by prompt version + model +
input, so unchanged inputs cost nothing. Every call's tokens and USD cost are recorded in
`agent_runs`. Resume text is treated as untrusted input in every prompt.

**Storage.** `STORAGE_BACKEND=local` (default, `LOCAL_STORAGE_DIR`) or `supabase` (private
bucket; create it with `supabase/storage.sql`). Downloads go through the API as
attachments.

## Job discovery (Phase 5)

The app discovers jobs from the **public job boards** of companies you choose, on
Greenhouse, Lever and Ashby (no keys and no scraping: each platform's documented public
JSON API).

1. **Pick companies** on the **Discovery** page: tick suggestions (Stripe, Figma, Ramp,
   OpenAI, ...) or add any board by platform + board name, the last part of its URL
   (`job-boards.greenhouse.io/<board>`, `jobs.lever.co/<board>`, `jobs.ashbyhq.com/<board>`).
   New boards are checked live before they are saved.
2. **Discover**: "Discover jobs now" crawls every tracked company; the scheduler re-crawls
   every `DISCOVERY_INTERVAL_MINUTES` (6 h), only companies that are due (incremental).
   Turn scheduled discovery off with `PATCH /api/v1/settings {"discovery_enabled": false}`.
3. **Browse** on the **Jobs** page: search title/company/location, filter by platform and
   workplace, open a job for its description, requirements, salary, dates and the raw
   board payload.

How it works (`backend/app/connectors/`, `agents/agent_2_job_discovery.py`,
`agents/agent_3_deduplication.py`, `services/discovery_service.py`):

- **Connectors** share one interface (`discover_jobs`, `normalize_job`, `validate_job`,
  `health_check`) and one HTTP client with timeouts, a response size cap, and retries with
  backoff for timeouts, 429 and 5xx (honouring `Retry-After`). Lever is paginated; an
  unknown board (404) is never retried. Adding Workday later = one new connector class.
- **Normalization**: plain-text description (HTML stripped), requirements extracted from
  requirement/qualification sections, remote/hybrid/on-site, employment type, yearly
  salary range (structured pay data first, then the posting text), posted date.
  Invalid postings (no title, unsafe URL, ...) are counted as skipped, never stored.
- **Deduplication**: same board + job id → update if its content hash changed, otherwise
  just `last_seen_at`; same URL as another job → skipped; same company + title + location
  fingerprint already found on another platform → skipped. `first_seen_at` never moves.
- **Expiry**: a job missing from a complete board response is marked `expired` (never
  if you applied); if it comes back it is revived. A response that looks truncated
  expires nothing.
- **Monitoring**: every run is a `discovery_runs` row with found / inserted / updated /
  unchanged / skipped / expired counts and per-company results; companies keep their
  last crawl status, error and consecutive failures; `GET /api/v1/discovery/health`
  (optionally `?probe=true`) reports per-platform health. One run at a time.

API: `/api/v1/jobs` (search, `/stats`, `/{id}`, `/{id}/raw`), `/api/v1/companies`
(+ `/directory`, `/suggested`), `/api/v1/discovery/runs`, `/api/v1/discovery/health`.

**Check it against the real job boards:** [docs/VALIDATION.md](docs/VALIDATION.md).

## Filtering and scoring (Phase 6)

Every discovery run continues as one pipeline (`services/pipeline_service.py`):
**Discovery → Deduplication → Filtering → Scoring**, each stage recorded in `agent_runs`.

1. **Set preferences** on the **Settings** page: preferred locations, workplace
   (any / remote only / hybrid / on-site), employment types, minimum and target salary,
   visa sponsorship, excluded companies and keywords, and (optionally) Claude scoring.
   Saving re-filters and re-scores your jobs in the background (`RESCORE_ON_CHANGE`).
2. **Browse matches** on the **Jobs** page: sorted by score, showing jobs that passed
   your filters by default ("Show": matches / filtered out / not filtered yet / all), with
   a minimum-score filter and a **Re-score** button. A job's page explains its score
   component by component and lists every filter check.

How it works:

- **Deduplication** (`FilteringService.mark_duplicates`): after the per-board checks of
  Phase 5, a sweep links postings that another board already supplied
  (`jobs.duplicate_of`), including ones inserted by concurrent crawls.
- **Agent 4, rule filter** (`agents/agent_4_rule_filtering.py`, pure): duplicate,
  company, keywords, location (aliases such as NYC/SF/US and US states), workplace,
  employment type, salary and sponsorship rules. Missing information never rejects a job.
  The decision (`filter_result`, `filter_reason`) is stored on the job; rejected jobs get
  status `filtered`. Shortlisted, skipped, applied and expired jobs are never re-filtered.
- **Agent 5, rule-based scoring** (`agents/agent_5_job_scoring.py`, pure, no tokens):
  skills (35), title relevance (25), seniority (15), location (15), salary (10). Components
  that cannot be judged are left out and the weights renormalised. Matched and missing
  skills and a per-component breakdown are stored in `job_scores`.
- **Claude scoring (optional)**: enable it in Settings with `ANTHROPIC_API_KEY` set. Only
  jobs whose rule score reaches your minimum are sent, best first, capped by
  `CLAUDE_SCORING_MAX_PER_RUN` (25), `CLAUDE_SCORING_MAX_PER_DAY` (100 real calls per
  rolling 24 h) and paced at `CLAUDE_SCORING_PER_MINUTE` (10). Answers are cached; a
  Claude score counts only while the inputs it saw are unchanged.
- Re-runs are cheap: filter decisions and scores store a hash of their inputs, so
  unchanged jobs are skipped.

API: `/api/v1/jobs?sort=score&filter_state=passed&min_score=60`, `/api/v1/jobs/{id}`
(with `filter_result` and `scores`), `POST /api/v1/scoring/runs`,
`GET /api/v1/scoring/summary`.

## Run it locally

Needs Docker, Python 3.14 and Node 26.

```bash
cp .env.example .env      # then set POSTGRES_PASSWORD (same password inside DATABASE_URL)
./scripts/dev.sh          # database + migrations + backend + frontend; first run installs deps
```

Open http://localhost:3000. To run the pieces by hand instead:

```bash
docker compose up -d --wait db
cd backend && source .venv/bin/activate
../scripts/init_db.sh     # migrate first
python -m app             # binds BACKEND_HOST:BACKEND_PORT, one worker
```

- Docs: http://127.0.0.1:8000/api/v1/docs (OpenAPI JSON at `/api/v1/openapi.json`)
- Probes: `GET /health` (liveness), `GET /health/ready` (database + migrations + scheduler)
- API: `/api/v1/resumes`, `/api/v1/profile`, `/api/v1/settings`, `/api/v1/jobs`, `/api/v1/companies`, `/api/v1/discovery`, `/api/v1/system/{info,jobs,tasks}`
- Auth: `AUTH_MODE=none` (default, loopback only) or `AUTH_MODE=api_key` with `API_KEY`
- Errors: `{"error": {"code", "message", "details"}}`; every response carries `X-Request-ID`

Layout (imports only point down; `tests/unit/test_architecture.py` enforces it):

| Layer | Packages |
|---|---|
| composition root | `main.py`, `bootstrap.py` (builds services on startup), `__main__.py` |
| HTTP | `routers/`, `dependencies.py` (dependency injection) |
| jobs | `scheduler/` (scheduled jobs, background task manager) |
| business logic | `services/`, `learning/` |
| workers | `agents/` (parser, profile; `agents/runs.py` records `agent_runs`) |
| queries | `repositories/` (never commit) |
| adapters | `documents/`, `storage/`, `llm/`, `parsing/`, `connectors/`, `automation/` |
| foundation | `core/` (config, logging, errors, database, auth, middleware) |
| data | `models/`, `schemas/`, `utils/` |

One request is one transaction (`get_db`); background work uses `session_scope()` and
never holds a transaction open during a Claude call. At startup, work interrupted by a
previous shutdown is marked failed/cancelled; a daily job prunes expired Claude cache
entries, and `agent_runs` and `discovery_runs` older than `AGENT_RUN_RETENTION_DAYS` (180).

Tests, lint and smoke test: see [docs/TESTING.md](docs/TESTING.md).

## Frontend

```bash
cd frontend && npm ci && npm run dev    # http://localhost:3000 (backend on :8000)
```

## Database quick start (Phase 2)

```bash
cp .env.example .env            # REQUIRED: set POSTGRES_PASSWORD (and keep DATABASE_URL in sync)
docker compose up -d db         # Postgres 19 on localhost:5432
cd backend && python3.14 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cd .. && ./scripts/init_db.sh   # alembic upgrade head
```

Tests:

```bash
cd backend
pytest tests/unit                       # schema + ORM consistency, no DB needed
# migration tests DROP tables - use a throwaway database:
docker compose exec db createdb -U jobhunter jobhunter_test
TEST_DATABASE_URL=postgresql+psycopg2://jobhunter:change_me@localhost:5432/jobhunter_test \
  pytest tests/integration/test_migrations.py
```

**Schema workflow.** `backend/schema.sql` is the readable reference for the current schema. Migration `0001` executes a frozen copy (`backend/migrations/sql/0001_initial.sql`); a unit test keeps the two identical. **Never edit a migration that has been applied: add a new Alembic revision instead** (then update `schema.sql` and the test that pins it). The ORM models mirror the schema. Requires PostgreSQL 15+ (developed and tested on 19).

**Upgrading from the Postgres 16 container.** `docker compose` now uses a new volume
(`pgdata19`); the old `pgdata` volume is left as is. Nothing is migrated automatically.
If the old database holds data you want, dump it before switching:

```bash
docker volume ls | grep pgdata          # e.g. ai-job-hunter_pgdata (the old one)
docker run --rm -d --name pg16 -v ai-job-hunter_pgdata:/var/lib/postgresql/data postgres:16-alpine
docker exec pg16 pg_dumpall -U jobhunter > backup.sql && docker stop pg16
docker compose up -d db && docker compose exec -T db psql -U jobhunter -d jobhunter < backup.sql
```

Otherwise just run `./scripts/init_db.sh` against the new, empty database.

**Validation.** `backend/tests/sql/validate_catalog.sql` (must return zero rows) and `backend/tests/sql/behavior.sql` (constraint/FK/cascade/trigger assertions) run inside `tests/integration/test_migrations.py`, or by hand:

```bash
psql "$DB" -f backend/tests/sql/validate_catalog.sql
psql "$DB" -v ON_ERROR_STOP=1 -f backend/tests/sql/behavior.sql
```
