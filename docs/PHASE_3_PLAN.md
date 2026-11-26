# Phase 3 plan: backend foundation

Status: **done** (2026-11-26). Decisions taken: personal, single-user use; API has
no auth by default and binds to loopback, with an `api_key` mode (and a single
`get_current_user` hook) for opening it up later; in-process scheduler, one worker.

Implemented beyond the original table: `core/security.py` (auth), `core/middleware.py`
(request id + access log), `core/paths.py`, `scheduler/background.py` (background
task manager), `routers/system.py` (info, scheduled jobs, background tasks), `/api/v1`
versioning with OpenAPI served under it.

## Baseline check

- Python 3.14 (originally verified on 3.13 before the toolchain upgrade), `pip install -r backend/requirements-dev.txt`: no conflicts.
- `ruff check app tests`: clean.
- `pytest`: 18 unit tests pass; 5 migration tests pass against PostgreSQL 16
  (`alembic upgrade/downgrade` round trip, catalog lint, behaviour SQL).
- `alembic upgrade head` on a fresh database seeds the single `settings` row (id = 1).

Fixed while checking: `test_job_and_application_history_protected` keyed foreign keys by
column name, so the composite FKs containing `job_id` overwrote the single-column
`RESTRICT` FK and the test failed against a correct model. It now inspects single-column
constraints only. Also removed an unused import and pinned pytest-asyncio's fixture loop
scope (needed before Phase 3 adds async tests).

## Scope: the 18 files marked `PLACEHOLDER - implemented in PHASE 3`

Build in this order; each layer only depends on the ones above it.

| # | File | What it provides |
|---|---|---|
| 1 | `app/core/config.py` | `Settings(BaseSettings)` reading `.env`: `DATABASE_URL` (normalise `postgres://` and `postgresql://` to `postgresql+asyncpg://`), `APP_ENV`, `CORS_ORIGINS` (comma list), Claude/Supabase/automation vars as optional so the app boots without them. Cached `get_settings()`. |
| 2 | `app/core/logging.py` | JSON logs in production, readable logs in development; request-id contextvar. |
| 3 | `app/core/exceptions.py` | `AppError` base (`NotFoundError`, `ConflictError`, `ValidationError`) + handlers returning one error envelope. Map `IntegrityError` (CHECK/FK violations) to 409/422 instead of 500. |
| 4 | `app/core/database.py` | Async engine + `async_sessionmaker(expire_on_commit=False)`; `pool_pre_ping`. If the URL points at a Supabase pooler (port 6543 / pgbouncer), pass `connect_args={"statement_cache_size": 0}`, since asyncpg prepared statements break under transaction pooling. |
| 5 | `app/core/dependencies.py` | `get_db()` (session per request, commit on success, rollback on error), `get_settings` dependency. |
| 6 | `app/utils/hashing.py` | `sha256_hex(text)` (matches the `^[0-9a-f]{64}$` CHECKs, e.g. `application_answers.question_hash`), stable JSON hashing for LLM cache keys. |
| 7 | `app/utils/text.py` | whitespace/unicode normalisation, `truncate`, slugify (shared by later dedup/normalizer work). |
| 8 | `app/schemas/common.py` | `ORMModel` base (`from_attributes=True`), error envelope, pagination params/response. |
| 9 | `app/schemas/settings.py` | `SettingsRead` and `SettingsUpdate` (all optional, PATCH semantics). Mirror every CHECK in `schema.sql` (remote preference and mode literals, threshold 0-100, cap 0-200, ISO currency, salary_min <= salary_target) so bad input is a 422, not a DB error. |
| 10 | `app/repositories/base.py` | Generic async `Repository[Model]`: get, list (limit/offset), add, update, delete. No commits inside repositories. |
| 11 | `app/repositories/settings_repository.py` | `get()` returns row 1 (re-create it if missing), `update(**fields)`. |
| 12 | `app/services/settings_service.py` | Business rules on top of the repo (e.g. salary order validated against the stored value on partial updates). |
| 13 | `app/routers/health.py` | `GET /health` (liveness, no DB) and `GET /health/ready` (`SELECT 1` + Alembic revision equals head). |
| 14 | `app/routers/settings.py` | `GET /api/settings`, `PATCH /api/settings`. |
| 15 | `app/scheduler/scheduler.py` | APScheduler `AsyncIOScheduler`, started/stopped from the FastAPI lifespan; disabled in tests via config. Single-process only (document: run one backend worker). |
| 16 | `app/scheduler/tasks.py` | Discovery job registered every `DISCOVERY_INTERVAL_MINUTES`, honours `settings.discovery_enabled`; body is a logged no-op until Phase 5. `max_instances=1`, `coalesce=True`. |
| 17 | `app/services/pipeline_service.py` | Orchestration skeleton: stage interface + `AgentRun` bookkeeping (insert `running`, finish with status/duration/error). Stages are wired in Phases 4-7. |
| 18 | `app/main.py` | App factory, lifespan (engine dispose, scheduler), CORS from config, exception handlers, include only the health and settings routers. |

Out of scope: the other routers (jobs, applications, resumes, profile, insights,
agent_runs), the LLM client and storage (Phase 4+).

## Tests to add

- Unit: config URL normalisation, hashing, text helpers, settings schema validation
  (every CHECK has a rejecting case).
- Integration (needs `TEST_DATABASE_URL`): `httpx.AsyncClient` + `ASGITransport` against
  the app, each test in a rolled-back transaction; health/ready, settings GET/PATCH,
  422 on invalid input, constraint violation mapped to 409/422, AgentRun bookkeeping.
- Keep migration tests in their own database: they drop all tables.

## Opening it up later

* Only you, from other devices: set `AUTH_MODE=api_key`, `API_KEY`, `BACKEND_HOST`, put it
  behind HTTPS, keep one worker (or move the scheduler to its own process).
* Other users: needs a migration adding an owner to user data (settings is a single
  row today), Supabase Auth JWTs in `get_current_user`, and row-level security.

## Running Postgres without Docker (e.g. cloud sessions)

```bash
PG=/usr/lib/postgresql/16/bin; D=/var/tmp/pgdata
mkdir -p $D && chown postgres $D && chmod 700 $D
su postgres -s /bin/bash -c "$PG/initdb -D $D -U postgres --auth=trust && $PG/pg_ctl -D $D -o '-k /var/tmp' -l /var/tmp/pg.log start"
psql -h localhost -U postgres -c "CREATE ROLE jobhunter LOGIN PASSWORD 'change_me' SUPERUSER" \
  -c "CREATE DATABASE jobhunter OWNER jobhunter" -c "CREATE DATABASE jobhunter_test OWNER jobhunter"
```
