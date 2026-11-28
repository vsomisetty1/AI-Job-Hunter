# AI Job Hunter

Personal job-search agent that runs on your own machine: parse a resume, discover jobs
(Greenhouse, Lever, Ashby), filter and score them (rule-based, optionally with Claude),
tailor resumes, generate application packages, fill application forms for you to review,
and learn from your outcomes. Every submission needs your explicit confirmation
(approval mode); there is no autonomous mode (ADR-014, ADR-016).

**Stack:** Next.js 16 + React 19 + TypeScript + Tailwind 4 (Node 26) · FastAPI on Python 3.14 · PostgreSQL 19 · Supabase Storage · Playwright · Claude API · Docker

**Version 0.10.0.** **Start here:** [PROJECT_STATE.md](PROJECT_STATE.md) (what exists now and
the roadmap), [AI_CONTEXT.md](AI_CONTEXT.md) (objectives, conventions, AI strategy),
[docs/architecture/](docs/architecture/) (ADR-001 to ADR-016).

**Run, back up, release:** [DEPLOYMENT.md](DEPLOYMENT.md) (Docker Compose or native, security
model), [BACKUP_AND_RECOVERY.md](BACKUP_AND_RECOVERY.md), [RELEASE_READINESS.md](RELEASE_READINESS.md)
(what is verified, what is not, the gates to 1.0).

CI runs on every push: lint, strict types, dependency audits, tests on Postgres 19 (incl.
real Chromium), the API contract between frontend and backend, a real-server smoke test, a
backup/restore round trip, shellcheck, the frontend build, and the Docker images with a
Compose smoke test: see [docs/TESTING.md](docs/TESTING.md).

## Build status

| Phase | Scope | Status |
|---|---|---|
| 1 | Folder structure + project config | Done |
| 2 | Database (schema, migrations, ORM) | Done |
| 3 | Backend foundation | Done |
| 4 | Resume intelligence (Agents 0, 1; resume versioning) | Done |
| 5 | Job discovery (Agents 2, 3; Agent 4 filtering moves to Phase 6) | Done |
| 6 | Rule filtering + scoring (Agents 4, 5; optional Claude scoring; learning moved to Phase 9) | Done |
| 7 | Application packages + approval workflow (Agents 6, 7, 8, 9) | Done |
| MVP | Validation on a real resume and real jobs | Done |
| 8 | Application automation, approval mode (Agent 10, Playwright) | Done |
| 9 | Learning and insights (interview and outcome tracking, Learning Agent, analytics, recommendations) | Done |
| 10 | Hardening and release readiness (local request guard, approval mode only, API contract, Docker/Compose, backup and restore, agent activity page) | Done |
| 11 | Real-use validation: real applications in approval mode, outcomes recorded | Next |
| 12 | End-to-end tests through the frontend (Playwright on the Compose stack) | Planned |
| 13 | Claude Code commands for AI work under the Pro plan (via the API) | Planned |
| 1.0 | Release | Planned |

The roadmap with exit criteria, and what comes after 1.0 (autonomous mode only behind a
new ADR, Workday), is in [PROJECT_STATE.md](PROJECT_STATE.md#13-roadmap-to-10).

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

**Check packages against your own resume and real postings:** [docs/MVP_VALIDATION.md](docs/MVP_VALIDATION.md) (`scripts/validate_mvp.py`; its output is personal and git-ignored).

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

## Application packages (Phase 7)

From a job page, **Generate package** builds everything needed to apply, for you to review:

1. **Tailored resume** (Agent 6): skills the job asks for move to the front in the posting's
   spelling, the most relevant bullets lead each role, the most relevant projects come first,
   and the summary opens with one sentence of profile facts. Every change is stored with its
   section, before/after, reason and time (see **Changes**). With "Reword with Claude", Claude
   may also reword bullets and the summary; each rewording is checked and dropped if it adds a
   skill or a number your resume does not have.
2. **Files** (Agent 7): PDF and DOCX of the tailored and the original resume, single-column
   and text-only for ATS parsers.
3. **Cover letter** (Agent 8, optional): 150–300 words built from your resume (or written by
   Claude and checked the same way), as text, PDF and DOCX. Every version is kept.
4. **Answers** (Agent 9): why this company, why you are qualified, salary, relocation,
   sponsorship, work authorization, years of experience and years per required skill, each
   with the facts it used. Anything your profile and settings cannot answer, or that is
   personal, is marked **needs your input** instead of guessed.

**Approval** (Packages page): review, edit answers, then **Approve** (the job's application
becomes `ready` in approval mode, for automation), **Reject** (with a
reason), **Regenerate** (a new version; the old one is kept as superseded) or **I applied
with this package**. Packages are filled into real forms on the Applications page.

API: `POST /api/v1/packages` (202), `GET /api/v1/packages?status=&job_id=`,
`GET /api/v1/packages/{id}`, `POST .../{id}/review|approve|reject|regenerate|mark-submitted`,
`PATCH .../{id}/answers/{answer_id}`, `GET .../{id}/files/{resume|cover-letter|original-resume}.{pdf|docx}`.

## Application automation, approval mode (Phase 8)

From **Applications** (or an approved package), **Fill application form** opens the job's
real Greenhouse, Lever or Ashby application in Chromium (Agent 10, Playwright):

1. **Open** the form (Greenhouse through its embeddable form, which works for every board).
2. **Upload** the tailored resume and cover letter (on Lever, which has no cover-letter
   upload, the letter goes into "Additional information"), and wait for sites that read
   the resume to finish, so they do not overwrite the answers.
3. **Fill** every field a fact supports. Fields are found by meaning (labels, ARIA,
   legends, nearby text, placeholders), not by hard-coded selectors; text boxes, dropdowns,
   React-select comboboxes, radio buttons, checkboxes, Yes/No buttons and uploads all work.
4. **Validate**: required fields still empty, the form's own error messages, CAPTCHAs.
5. **Stop** with a screenshot and the **review screen**: resume and cover letter status,
   answers inserted (and where each came from), missing fields, validation problems.
   **Edit** any field (it changes in the open form), **Retry** (reopen and refill from the
   checkpoint), **Cancel**, or **Submit**, which needs an explicit confirmation.

What it never does: submit without your confirmation (the database refuses it too), type a
package answer still marked "needs your input", tick consent or certification boxes, or
guess voluntary self-identification (it picks "decline" where offered). Failures (browser
crash, timeout, network, upload refused, job closed, changed form, CAPTCHA, no
confirmation) are recorded with what to do next; transient ones retry automatically, a
submission never does. There is no autonomous mode yet.

Setup: `playwright install chromium` in the backend virtualenv (once). `AUTOMATION_HEADLESS=false`
shows the browser, which is how you solve a CAPTCHA. See ADR-014 and
[docs/AUTOMATION_VALIDATION.md](docs/AUTOMATION_VALIDATION.md).

API: `GET /api/v1/automation/{status,queue}`, `POST /api/v1/automation/submissions` (202),
`GET .../submissions?status=`, `GET .../submissions/{id}`, `PATCH .../{id}/fields`,
`POST .../{id}/retry|cancel`, `POST .../{id}/submit` with `{"confirm": true}`,
`GET .../{id}/screenshots/{n}`, `GET /api/v1/automation/logs?submission_id=&level=`.

## Learning and insights (Phase 9)

**Interviews** (`/insights/pipeline`): every submitted application by where it stands.
Record what happened: a recruiter response, recruiter / phone screens, technical, hiring
manager, onsite and final rounds (scheduled, completed, cancelled or no-show), an offer, a
rejection or a withdrawal. The application's milestones and status follow from those
events; edit or delete one and everything recomputes. The **outcome timeline** shows
packages generated and approved, submissions and every event.

**Dashboard** (`/`): response, interview and offer rates with 95 % intervals, the funnel
(generated -> approved -> submitted -> response -> interview -> offer), score accuracy (does
the job score predict interviews?), skill correlations, results by job family and workplace,
and the trend. **Companies**, **Resume performance** (resume versions, cover letter,
tailoring, package versions, how you applied) and **Job boards** break the same rates down.
Set a company's industry there to compare industries; the app never guesses it.

**Insights and recommendations** (`/insights/recommendations`) come only from your data and
only when they hold up: enough applications per group, a real difference, and Fisher's exact
test corrected for the number of comparisons. Each shows its counts. Recommendations (score
threshold, job families, industries, boards, cover letters, skills to add *if you have
them*, outcomes to record) link to where to act; nothing is changed for you. The **Learning
Agent** runs daily (or "Run the Learning Agent") and keeps a snapshot history. See ADR-015.

API: `GET /api/v1/applications`, `GET /api/v1/applications/{id}`,
`POST|PATCH|DELETE /api/v1/applications/{id}/events[/{event_id}]`,
`GET /api/v1/applications/timeline`, `GET /api/v1/insights{,/summary,/companies,/boards,/resumes,/recommendations,/history}`,
`PUT /api/v1/insights/recommendations/{key}/state`, `POST /api/v1/insights/refresh`,
`PATCH /api/v1/companies/{id}` with `industry`.

## Hardening and release readiness (Phase 10)

- **Local-only by construction** (ADR-016): requests for any host name other than
  `localhost`/`127.0.0.1`/`::1` are refused (DNS rebinding), writes from other web origins
  are refused (CSRF), and pages and API responses cannot be framed. Compose publishes every
  port on 127.0.0.1 only.
- **Approval mode only**: the settings API refuses `application_mode`, `auto_apply_threshold`
  and `daily_application_cap`; migration 0008 makes the database refuse `AUTONOMOUS_MODE`.
- **API contract**: `frontend/src/types/api.gen.ts` is generated from the backend's OpenAPI
  spec (`python scripts/gen_api_contract.py`); typecheck and tests fail when the frontend's
  types or calls drift from the backend.
- **Docker**: real backend and frontend images and a full Compose stack (DEPLOYMENT.md).
- **Backups**: `scripts/backup.sh` / `scripts/restore.sh`, tested by CI (BACKUP_AND_RECOVERY.md).
- **Agent activity page** (`/activity`, `GET /api/v1/agent-runs{,/summary,/agents}`): every
  agent run and pipeline stage with outcome, duration, tokens and cost.

## Run it

With Docker only (DEPLOYMENT.md):

```bash
cp .env.example .env                    # then set POSTGRES_PASSWORD
docker compose up -d --build --wait     # http://localhost:3000
```

For development (Docker, Python 3.14 and Node 26):

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
- API: `/api/v1/resumes`, `/api/v1/profile`, `/api/v1/settings`, `/api/v1/jobs`, `/api/v1/companies`, `/api/v1/discovery`, `/api/v1/scoring`, `/api/v1/packages`, `/api/v1/automation`, `/api/v1/applications`, `/api/v1/insights`, `/api/v1/agent-runs`, `/api/v1/system/{info,jobs,tasks,storage}`
- Auth: `AUTH_MODE=none` (default, loopback only) or `AUTH_MODE=api_key` with `API_KEY`;
  `ALLOWED_HOSTS` and `CORS_ORIGINS` guard every request (DEPLOYMENT.md, section 4)
- Errors: `{"error": {"code", "message", "details"}}`; every response carries `X-Request-ID`

Layout (imports only point down; `tests/unit/test_architecture.py` enforces it):

| Layer | Packages |
|---|---|
| composition root | `main.py`, `bootstrap.py` (builds services on startup), `__main__.py` |
| HTTP | `routers/`, `dependencies.py` (dependency injection) |
| jobs | `scheduler/` (scheduled jobs, background task manager) |
| business logic | `services/`, `learning/` |
| workers | `agents/` (Agents 0–10; `agents/runs.py` records `agent_runs`) |
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

## Database

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

**Schema workflow.** `backend/schema.sql` is the readable reference for the schema at the
latest migration (0008); an integration test checks it against a migrated database. Each
Alembic revision executes a frozen SQL file in `backend/migrations/sql/`, pinned by SHA-256 in
`tests/unit/test_schema_sql.py`. **Never edit a migration that has been applied: add a new
revision instead** (then update `schema.sql`, the ORM models and the pin). Requires
PostgreSQL 15+ (developed and tested on 19).

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
