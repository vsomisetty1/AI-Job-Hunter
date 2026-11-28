# AI context

Orientation for anyone, human or AI assistant, picking up this repository cold. Read it
with [PROJECT_STATE.md](PROJECT_STATE.md), which covers what exists today, and the ADRs in
[docs/architecture/](docs/architecture/), which explain why.

## Project objectives

AI Job Hunter is a **personal, single-user job-search agent**. It should:

1. Understand the user from their resume: parse it, then build a career profile.
2. Discover relevant jobs continuously from company job boards.
3. Filter and score those jobs against the profile and preferences.
4. Prepare application packages: tailored resume, cover letter, answers.
5. Apply in **approval mode**: the app fills the form, the user reviews and confirms each
   submission. Autonomous mode (above a score threshold, under a daily cap) is a possible
   post-1.0 goal; it is **not built** and is blocked in the API and the database until a new
   ADR enables it (ADR-014, ADR-016).
6. Learn from outcomes to improve targeting.

It runs on the user's own machine. **It is not a public, multi-user service.**

## MVP scope

The MVP was Phases 1–7 (resume intelligence, discovery, filtering and scoring, application
packages); Phases 8–10 added approval-mode automation, learning from outcomes, and release
hardening. The roadmap to 1.0 is in PROJECT_STATE.md §13.

| In scope | Out of scope (for now) |
|---|---|
| One user and one database; loopback API | Multi-user accounts, public hosting, SaaS |
| Greenhouse, Lever, Ashby public boards | Workday, LinkedIn/Indeed scraping, aggregators |
| Boards the user chooses to track | Crawling "all companies" |
| Deterministic pipeline with optional Claude | Mandatory paid AI for routine work |
| Approval mode (user confirms every submission) | Autonomous mode, unattended mass-applying |
| Docker Compose on your own machine, loopback only | LAN, server or cloud deployment |

## Architecture principles

1. **A modular monolith with enforced layers** (ADR-001). Imports only point down, and
   `tests/unit/test_architecture.py` fails the build otherwise.
2. **PostgreSQL is the only state store** (ADR-002). There is no Redis and no queue. The schema
   is reviewed SQL, and the migrations are frozen files.
3. **Short transactions** (ADR-003): one request is one transaction, repositories never
   commit, and no transaction stays open across a network or LLM call.
4. **Single user, local first** (ADR-004, ADR-016). There is no auth on loopback, and an
   API key otherwise. Every request passes the local request guard: Host allowlist (DNS
   rebinding), cross-site writes refused (CSRF), no framing.
5. **In-process jobs** (ADR-005): APScheduler plus a background task manager, with one worker.
   Startup recovers interrupted work.
6. **Deterministic first, AI optional** (ADR-006). Every feature works without Claude.
   Claude improves quality where it is cheap and safe, is cached and cost-tracked, and
   receives the minimum personal data.
7. **Treat every external input as hostile** (ADR-007). Uploads are validated and
   extracted in a sandbox. Job-board HTML is reduced to text, and URLs are checked
   before they are linked.
8. **Providers sit behind interfaces** (ADR-008). Connectors, storage backends and
   platform adapters are each one class per provider, and no provider logic leaks
   outside them.
9. **Observable by default.** `agent_runs`, `discovery_runs`, company crawl status,
   request IDs and structured logs let you see what happened without a debugger.
10. **Tests ship with features** (ADR-010). Tests run against real Postgres, external
    services are never called in CI, and CI is extended in every phase.
11. **One contract between frontend and backend** (ADR-016). The frontend's types are
    checked against types generated from the backend's OpenAPI spec.

## Coding conventions

**Python (backend/)**
- Python 3.14 with type hints everywhere. `mypy --strict` must pass (`mypy` in `backend/`).
- ruff with rule sets E, F, W, I, B, UP, ASYNC, BLE and S (bandit), line length 100.
  `ruff format` is the formatter.
- Pydantic v2 for every API body and response:
  - request bodies extend `APIModel` (rejects unknown fields, trims strings)
  - responses built from ORM objects extend `ORMModel`
- Errors raise `AppError` subclasses (`NotFoundError`, `ConflictError`,
  `DomainValidationError`, `ServiceUnavailableError`, or one with its own `code` and
  `status_code`). Never return error dicts by hand.
- Dependencies are injected through the `Annotated[...]` aliases in `app/dependencies.py`.
  Tests override them with `app.dependency_overrides`.
- Never name a method `list`: it shadows the built-in in annotations. Use `list_companies`
  and the like.
- Async I/O only (asyncpg, httpx). CPU-heavy or untrusted parsing runs in the sandbox
  process.
- Logging goes through `logging.getLogger(__name__)`. Never log secrets or resume
  contents.
- Pure logic (parsers, dedup, normalizers) lives in modules with no I/O so it can be
  unit-tested.

**TypeScript (frontend/)**
- Strict TypeScript; types that mirror backend schemas live in `src/types/index.ts`. After
  changing a backend request/response model or route, run
  `python scripts/gen_api_contract.py` (backend venv) and commit `src/types/api.gen.ts`; add
  new response types to the checks in `src/types/contract.ts`. CI fails on drift.
- All HTTP goes through `apiFetch` (`src/lib/api/client.ts`), and data fetching uses SWR
  hooks in `src/hooks/`.
- Never render backend or third-party text as HTML. Link URLs only through `safeUrl`.
- Components are small and live by feature (`src/components/<feature>/`). Vitest tests
  sit next to them.

**Database**
- Schema changes need a new Alembic revision that executes a new frozen SQL file in
  `migrations/sql/`. Then update `schema.sql`, the ORM model, the SHA-256 pin in
  `tests/unit/test_schema_sql.py`, and `tests/sql/*` where relevant.
- **Never edit an applied migration.**
- Enum-like columns are `text` with a CHECK constraint. Constraints are named
  `ck_`/`uq_`/`fk_`/`ix_`/`trg_`.

## Repository conventions

- **Layout:**
  - `backend/` holds the FastAPI app, migrations and tests.
  - `frontend/` holds the Next.js app.
  - `scripts/` holds `dev.sh`, `init_db.sh`, `smoke_backend.sh`, `smoke_compose.sh`,
    `backup.sh`, `restore.sh` (+ `lib/common.sh`, `test_backup_restore.sh`),
    `gen_api_contract.py` and the real-world `validate_*` scripts.
  - `docs/` and `supabase/` hold supporting material.
- **No placeholders:** Phase 10 implemented or removed every Phase 1 stub, and
  `tests/unit/test_repository_hygiene.py` fails if one appears. Do not add empty modules for
  future work.
- **Version:** one version in `backend/pyproject.toml`, `Settings.app_version` and
  `frontend/package.json` (a test keeps them equal); bump it when a phase ships.
- **Commits:** conventional style (`feat:`, `chore:`, `docs:`, `ci:`). Each phase is one
  feature commit that includes its tests, CI changes and docs.
- **Versions:** use the latest stable release of every dependency, pinned exactly. Any
  holdback is recorded with its reason in `docs/TESTING.md` ("Toolchain versions").
- **CI must stay green:** lint, format, strict types, audit, tests with no skips, smoke
  test, and the frontend build.
- **Secrets** live only in `.env`, which is git-ignored. `.env.example` documents every
  setting.
- **Branching:** work happens on feature branches. Pull requests are opened only when the
  owner asks.

## AI integration strategy

**Goal: the app costs nothing to run, and the owner's Claude Pro subscription is the only
AI cost.**

1. **Automatic work is deterministic.** Discovery, normalization, dedup, filtering and
   baseline scoring use no tokens.
2. **The Claude API is optional** (`ANTHROPIC_API_KEY`). When it is set, the app uses it
   only where quality clearly improves:
   - enriching weak resume sections
   - profile inference and career analysis
   - (later) scoring a shortlist and writing tailored text
3. **API calls are disciplined:**
   - structured outputs into Pydantic models
   - SDK retries
   - refusal fallback
   - a Postgres response cache keyed by prompt version, model and input
   - per-call token and USD cost recorded in `agent_runs`
   - PII minimization: the profile prompts get no name, contact details or links
   - resume text (and, from Phase 6, job text) is treated as untrusted input in every prompt
4. **Subscription-quality AI runs through Claude Code, not the app.** AI-heavy steps
   (scoring a shortlist, tailoring, cover letters) are meant to be run by the owner as
   Claude Code commands under their Pro plan. Those commands read and write through the
   app's API.
5. **Never wire Claude Pro/Max OAuth or session credentials into the app.**
   Subscription auth is for Claude.ai and Claude Code only.
6. **Fully automatic AI is opt-in.** Scheduled AI scoring or autonomous applying runs only
   if the owner adds an API key, ideally with a Console spend cap.

**Truthfulness rules learned in MVP validation** (apply to any new generator, rule-based or
Claude):
- Claim a skill as *used* only where a resume line describes using it: a mention after
  "future", "planned", "exposure to", "familiar with" or before "-ready"/"concepts" is intent,
  not use (`relevance.strong_mentions`).
- When a sentence promises evidence for a skill, the next quoted line must show it.
- Use job titles as held, without arrangement qualifiers like "(Contract)" in prose
  (`role_name`), and never invent a composite title.
- Evidence is picked per posting (`relevance.JobTerms`), so two letters for two jobs differ.
- Personal data from a real resume never goes into the repository: validation output lives
  in the git-ignored `validation-output/`.

**Learning rules (Phase 9, ADR-015)** for any analysis or advice shown to the user:
- Use only recorded data (the user's applications, packages and outcomes). Never infer
  facts such as a company's industry; let the user set them.
- State a difference only when it passes the gates in `learning/insights.py` (group sizes,
  minimum effect, Fisher exact + Holm); show the counts and the test with it. With too
  little data, say so.
- Recommendations link to where the user can act; never change settings, profile or
  applications automatically, and never suggest adding a skill except "if you have it".
- Outcome milestones are derived from interview events: never set them directly.

**Automation rules (Phase 8, ADR-014, ADR-016)** for anything that touches an application form:
- Approval mode only: nothing is submitted without the user's explicit confirmation; the
  database enforces it (`application_submissions.mode`, `settings.application_mode` and
  `applications.application_mode` = APPROVAL_MODE, `confirmed_at` before submitting), and the
  settings API refuses the autonomous fields. Do not add a code path that submits otherwise
  without a new ADR.
- Find fields by meaning (labels, ARIA, legends, nearby text), never by hard-coded
  selectors; platform adapters hold only what is truly platform-specific.
- Never guess: no fact, no answer; never type a "needs review" package answer; never tick
  consent; decline or skip voluntary self-identification.
- Never retry a submission automatically; an unconfirmed one fails as `unconfirmed`.
- Real-site testing uses a synthetic persona and documents (attaching a file uploads it to
  the ATS), review mode only: `scripts/validate_automation.py`.

Models are configurable (`CLAUDE_MODEL_SCORING`, `CLAUDE_MODEL_WRITING`,
`CLAUDE_MODEL_ANALYSIS`). The defaults are the current small, mid and large models.

## Supported ATS providers

Only the providers' public, unauthenticated posting APIs are used for discovery. There is
no HTML scraping.

| Provider | Discovery API | Notes |
|---|---|---|
| Greenhouse | `GET boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true&pay_transparency=true` | Whole board in one response; pay ranges in cents; entity-escaped HTML |
| Lever | `GET api.lever.co/v0/postings/{board}?mode=json&skip=&limit=` (EU: `api.eu.lever.co`) | Paginated; yearly `salaryRange` |
| Ashby | `GET api.ashbyhq.com/posting-api/job-board/{board}?includeCompensation=true` | Whole board; `isListed`; structured compensation |

A board is identified by `(source, slug)`, where the slug is the last part of the public
careers URL. Application automation (Phase 8) uses the same three providers through
`automation/platforms/`.

## Why Workday is deferred

Workday is the most common enterprise ATS, but it is deliberately not supported yet:

- **No single public board API.** Each employer is its own tenant
  (`<tenant>.wd<N>.myworkdayjobs.com/<site>`). Finding jobs needs the tenant, the data
  centre and the site name, which have to be discovered per company. The JSON endpoint
  behind the careers site is undocumented and can change without notice.
- **Operational risk.** Tenants rate-limit and bot-protect aggressively, and the request
  shape (paged POST with facets) differs from the simple GET boards above. That brings a
  higher maintenance burden and a higher risk of being blocked.
- **Applying is much harder.** Workday applications require a candidate account per
  employer, multi-step wizards, and document parsing that overwrites fields. This is the
  hardest automation target and the least compatible with safe approval-mode flows.
- **The MVP is better served elsewhere.** Greenhouse, Lever and Ashby cover a large share
  of tech-company postings with stable public APIs.

The design keeps the door open:
- a Workday connector is one new `Connector` subclass plus a registry entry, with a
  `source` CHECK update in a migration;
- a platform adapter slot exists in `automation/platforms/`.

Revisit after 1.0, starting with discovery only (see ADR-008).

## Roadmap

The single, current roadmap (with exit criteria) is **PROJECT_STATE.md §13**: Phase 11
real-use validation in approval mode, Phase 12 end-to-end tests, Phase 13 Claude Code
commands, then 1.0. After 1.0, each with its own decision: autonomous mode (new ADR),
Workday discovery, more providers, full-text search, optional multi-user mode.
