# Testing and CI

CI (`.github/workflows/ci.yml`) runs on every push and pull request. A red
check means do not merge.

| Job | Steps |
|---|---|
| Backend | `pip check`, `ruff check` (incl. bandit security rules), `pip-audit`, `ruff format --check`, `mypy --strict`, `pytest` against a real **Postgres 19** (fails if any test is skipped), then `scripts/smoke_backend.sh` (starts `python -m app`, calls the main endpoints, uploads a resume and waits for the profile) |
| Frontend | `npm ci`, `npm audit`, `typecheck`, `lint`, `npm test` (Vitest + Testing Library), `next build` |

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
- **CI is extended** when a phase adds something new to verify (Phase 5 added the weekly
  `live-connectors.yml` workflow that runs `tests/live` against the real job boards;
  Phase 8 installs Chromium in the backend job for the browser tests; Phase 9 builds the
  Docker images; Phase 10 adds frontend-through-backend e2e).
- The phase summary states what is **not** covered.

## Test layout

- `tests/unit/test_architecture.py`: layer rules, no package import cycles, every module
  imports on its own.
- `tests/unit/`: pure logic (parsing, validation, sandbox, storage, Claude client with a
  fake SDK, app wiring). Test documents are generated at runtime by
  `tests/fixtures/documents.py`, including hostile ones (JavaScript PDFs, macro DOCX,
  zip bombs, XXE, encrypted PDFs).
- `tests/integration/`: real Postgres. `db_app` runs each test in a rolled-back
  transaction; `build_live_app` (resume flows with concurrent background tasks) uses the
  real pool and empties user tables before and after.
- Claude is never called in CI: `tests/fakes.py` (`FakeAnthropic`) answers by output schema.
- Job boards are never called in CI: `tests/fixtures/boards/` holds realistic Greenhouse,
  Lever and Ashby responses (same shapes as the live APIs, synthetic companies) served by
  `respx`. `tests/unit/test_connectors.py` covers pagination, retries, errors and
  normalization; `tests/unit/test_deduplication.py` the dedup rules;
  `tests/integration/test_discovery.py` the whole pipeline on Postgres (insert, unchanged,
  update, expire, revive, incomplete responses, cross-board and URL duplicates, failure
  isolation, one run at a time, scheduled incremental refresh, the API).
- Phase 6 (filtering and scoring): `tests/unit/test_rule_filtering.py` (every Agent 4
  rule, location aliases and US states, sponsorship phrases, fingerprints) and
  `tests/unit/test_scoring.py` (every Agent 5 component, weighting, fingerprints, the
  Claude rate limiter, cache hits bypassing pacing, clamping);
  `tests/integration/test_pipeline.py` (filter decisions and status moves, cross-board
  duplicate links, rule scores with skip-unchanged, Claude shortlist scoring with usage,
  caching, staleness, per-run and daily caps, failure isolation, the full pipeline from a
  mocked board, the scheduled cycle) and `tests/integration/test_api.py` (score sorting
  and filter controls, job detail breakdown, effective Claude vs. rule score, scoring
  run/summary endpoints, settings and profile edits re-scoring in the background).
  `tests/fixtures/jobs.py` seeds companies, jobs, profiles and settings. Migration 0004 is
  covered both ways in `test_migrations.py`. The smoke script also runs a scoring pass.
- Phase 7 (application packages): `tests/unit/test_resume_tailoring.py` (truthfulness guard,
  deterministic tailoring, change log, headline facts, a randomized truthfulness property
  check, Claude rewordings accepted or dropped), `test_resume_rendering.py` (PDF text in
  reading order via pdfplumber, no unreadable glyphs, escaping, DOCX bullets, letters),
  `test_cover_letters.py` (150–300 words, quoted evidence, no missing skills, Claude letter
  checks), `test_application_answers.py` (every question type, evidence, review flags, polish
  checks); `tests/integration/test_packages.py` (full generation through the API with files,
  one live package, missing inputs, review/approve/submit with the applications row and events,
  reject/regenerate/supersede, interrupted generation, Claude path with rejected inventions,
  no-key fallback). Migration 0005 is covered both ways; the smoke script generates, downloads,
  reviews and approves a package on the real server. Frontend: `Packages.test.tsx`.
- MVP validation: `tests/integration/test_lifecycle.py` (package delete rules, artifacts an
  application uses are kept, retention pruning, resume file cleanup, orphan sweep with grace
  period, storage report/cleanup endpoints); `test_storage.py` (`list_files`);
  `test_scoring.py` (shrinkage, neutral unknown skills, function mismatch);
  `test_cover_letters.py` / `test_application_answers.py` (relevance-ranked evidence, skill
  lead backed by the next line, plan/exposure mentions not claimed, arrangement qualifiers
  dropped); `test_packages.py` (expired job cannot be approved); `test_discovery.py` (empty
  board note). The smoke script also checks package delete (409 when approved) and the
  storage endpoints. Real-data checks are manual: `scripts/validate_mvp.py` (see
  [MVP_VALIDATION.md](MVP_VALIDATION.md)); its output is personal and git-ignored.
- Phase 8 (application automation): `tests/unit/test_automation.py` (labels and required
  markers from real forms, concepts, option choice by meaning, every "never guess" rule,
  education, years and ranges, US authorization, recovery classification and retries,
  checkpoints, the session registry, adapter URLs); `tests/browser/` drives a **real
  Chromium** (Playwright) against mock Greenhouse, Lever and Ashby pages
  (`tests/fixtures/ats.py`, served at the real hosts through request routing, no network):
  `test_form_engine.py` (every labelling technique and control type, fill and read back,
  validation) and `test_agent_10_mock_ats.py` (fill, upload, review, edit, confirmed submit
  sent exactly once, Lever's resume parse overwriting values, reload mid-fill, closed job,
  changed form, upload error, rejection, CAPTCHA, no confirmation, browser crash and
  relaunch, cookies); `tests/integration/test_automation_api.py` (the API workflow on
  Postgres + Chromium: queue, start, review, edit, confirm-only submit and its effects on
  application/package/job, cancel, retry with saved edits, automatic retry of transient
  failures, unconfirmed submissions never resent, idle timeout, startup recovery, rules);
  the migration test proves the database refuses autonomous mode and unconfirmed
  submissions. CI installs Chromium (`python -m playwright install --with-deps chromium`);
  locally, `AUTOMATION_BROWSER_PATH` can point at another Chromium. Live forms are checked
  by hand in review mode: `scripts/validate_automation.py` (see
  [AUTOMATION_VALIDATION.md](AUTOMATION_VALIDATION.md)).
- Background re-scoring on settings/profile changes is off in the default test app
  (`rescore_on_change=False`, like the scheduler), because the rolled-back `db_app`
  shares one connection; the tests that cover it use the live-pool app.
- `tests/live/` (marker `live`, deselected by default) checks the connectors against the
  real platforms: `pytest -m live tests/live`. For the full app, see
  [VALIDATION.md](VALIDATION.md).

## Running locally

```bash
cd backend && source .venv/bin/activate
ruff check app tests migrations && ruff format --check app tests migrations && mypy
python -m playwright install chromium   # once: browser tests and automation
TEST_DATABASE_URL=postgresql+psycopg2://jobhunter:<password>@localhost:5432/jobhunter_test pytest
DATABASE_URL=postgresql://jobhunter:<password>@localhost:5432/jobhunter ../scripts/smoke_backend.sh
pytest -m live tests/live       # optional: real Greenhouse/Lever/Ashby APIs (needs internet)

cd ../frontend && npm ci && npm run typecheck && npm run lint && npm test && npm run build
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

`playwright` (Python) is 1.65.2, the latest; `pytest-playwright` was removed in Phase 8 (a
sync-API plugin nothing used; the browser tests use their own async fixtures).

Re-check these when upgrading.
