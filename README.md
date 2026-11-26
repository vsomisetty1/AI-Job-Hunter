# AI Job Hunter

Autonomous job-search agent: parse a resume, discover jobs (Greenhouse, Lever, Ashby),
score them with Claude, tailor resumes, generate application packages, and apply
(approval or autonomous mode). Workday can be added later via the connector and
platform-adapter interfaces.

**Stack:** Next.js + TypeScript + Tailwind · FastAPI · PostgreSQL · Supabase Storage · Playwright · Claude API · Docker

## Build status

| Phase | Scope | Status |
|---|---|---|
| 1 | Folder structure + project config | Done |
| 2 | Database (schema, migrations, ORM) | Done |
| 3 | Backend foundation | Done |
| 4 | Resume system (Agents 0, 1, 6, 7, 8) | Pending |
| 5 | Job discovery (Agents 2, 3, 4) | Pending |
| 6 | Scoring + learning (Agent 5) | Pending |
| 7 | Application automation (Agents 9, 10) | Pending |
| 8 | Frontend | Pending |
| 9 | Deployment | Pending |
| 10 | Testing | Pending |

Files containing `PLACEHOLDER - implemented in PHASE N` are stubs filled in by that phase.

## Backend quick start (Phase 3)

```bash
cd backend && source .venv/bin/activate
../scripts/init_db.sh                                   # migrate first
python -m app                                           # binds BACKEND_HOST:BACKEND_PORT, one worker
```

- Docs: http://127.0.0.1:8000/api/v1/docs (OpenAPI JSON at `/api/v1/openapi.json`)
- Probes: `GET /health` (liveness), `GET /health/ready` (database + migrations + scheduler)
- API: `/api/v1/settings` (GET, PATCH), `/api/v1/system/{info,jobs,tasks}`
- Auth: `AUTH_MODE=none` (default, loopback only) or `AUTH_MODE=api_key` with `API_KEY`
- Errors: `{"error": {"code", "message", "details"}}`; every response carries `X-Request-ID`

Layout: `core/` (config, logging, errors, database, auth, DI, middleware) ->
`routers/` (HTTP only) -> `services/` (business rules) -> `repositories/` (queries,
never commit) -> `models/`. One request is one transaction (`get_db`); background
work uses `session_scope()`. Scheduled jobs live in `scheduler/tasks.py`, ad-hoc
async work goes through `BackgroundTaskManager` (`scheduler/background.py`), and
agent invocations are recorded in `agent_runs` by `services/pipeline_service.py`.

Tests: `pytest` (unit) plus `TEST_DATABASE_URL=... pytest` for the database-backed
API and migration tests. Lint: `ruff check app tests migrations`.

## Database quick start (Phase 2)

```bash
cp .env.example .env            # REQUIRED: set POSTGRES_PASSWORD (and keep DATABASE_URL in sync)
docker compose up -d db         # Postgres 16 on localhost:5432
cd backend && python -m venv .venv && source .venv/bin/activate
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

**Schema workflow.** `backend/schema.sql` is the readable reference for the current schema. Migration `0001` executes a frozen copy (`backend/migrations/sql/0001_initial.sql`); a unit test keeps the two identical. **Never edit a migration that has been applied: add a new Alembic revision instead** (then update `schema.sql` and the test that pins it). The ORM models mirror the schema. Requires PostgreSQL 15+.

**Validation.** `backend/tests/sql/validate_catalog.sql` (must return zero rows) and `backend/tests/sql/behavior.sql` (constraint/FK/cascade/trigger assertions) run inside `tests/integration/test_migrations.py`, or by hand:

```bash
psql "$DB" -f backend/tests/sql/validate_catalog.sql
psql "$DB" -v ON_ERROR_STOP=1 -f backend/tests/sql/behavior.sql
```
