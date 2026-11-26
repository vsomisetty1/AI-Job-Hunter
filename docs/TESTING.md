# Testing and CI

CI (`.github/workflows/ci.yml`) runs on every push and pull request. A red
check means do not merge.

| Job | Steps |
|---|---|
| Backend | `pip check`, `ruff check`, `ruff format --check`, `pytest` against a real **Postgres 19** (fails if any test is skipped), then `scripts/smoke_backend.sh` (starts `python -m app` and calls the main endpoints) |
| Frontend | `npm ci`, `typecheck`, `lint`, `next build` |

Warnings are errors in pytest (`filterwarnings = ["error"]`), so a deprecation from
our code or a dependency upgrade fails CI instead of being ignored.

## Rule for every phase

Each phase ships its tests and its CI changes in the same commit as the feature:

- **Unit tests** for pure logic (parsers, scoring, normalisers, schemas).
- **Integration tests** (`tests/integration/`, use the `db_app` fixture) for anything that
  touches the database or the API. Each test runs in a rolled-back transaction.
- **External services are never called in CI.** Claude API, Supabase and job boards are
  mocked (`respx` for HTTP); one opt-in test per integration may hit the real service
  when its key is present, and is skipped in CI by marker, not by accident.
- **CI is extended** when a phase adds something new to verify (e.g. Phase 7 adds a
  Playwright job with browsers; Phase 8 adds frontend unit/e2e tests; Phase 9 builds
  the Docker images).
- The phase summary states what is **not** covered.

## Running locally

```bash
cd backend && source .venv/bin/activate
ruff check app tests migrations && ruff format --check app tests migrations
TEST_DATABASE_URL=postgresql+psycopg2://jobhunter:<password>@localhost:5432/jobhunter_test pytest
DATABASE_URL=postgresql://jobhunter:<password>@localhost:5432/jobhunter ../scripts/smoke_backend.sh

cd ../frontend && npm ci && npm run typecheck && npm run lint && npm run build
```

Create the throwaway test database once: `docker compose exec db createdb -U jobhunter jobhunter_test`.
Never point `TEST_DATABASE_URL` at your real database: migration tests drop every table.

## Toolchain versions

Latest stable at the time of writing (2026-11-26), with these exceptions held back
for compatibility:

| Package | Pinned | Latest | Why |
|---|---|---|---|
| httpx | 0.28.1 | 0.29.0 | `supabase` requires `httpx<0.29` |
| eslint | 9.39.5 | 10.x | `eslint-config-next` 16 plugins support ESLint <= 9 |
| typescript | 6.0.3 | 7.0.x | `typescript-eslint` (used by `eslint-config-next`) does not support TS 7 yet |
| apscheduler | 3.11.3 | 4.0 pre-release | 4.x is not stable |

Re-check these when upgrading.
