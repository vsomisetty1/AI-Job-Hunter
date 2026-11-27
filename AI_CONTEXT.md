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
5. Apply, in **approval mode** (the user confirms each application) or **autonomous mode**
   (above a score threshold, under a daily cap).
6. Learn from outcomes to improve targeting.

It runs on the user's own machine. **It is not a public, multi-user service.**

## MVP scope

The MVP is Phases 1–7: resume intelligence, discovery, filtering and scoring, application
packages, and approval-mode automation for the supported ATS providers.

| In scope | Out of scope (for now) |
|---|---|
| One user and one database; loopback API | Multi-user accounts, public hosting, SaaS |
| Greenhouse, Lever, Ashby public boards | Workday, LinkedIn/Indeed scraping, aggregators |
| Boards the user chooses to track | Crawling "all companies" |
| Deterministic pipeline with optional Claude | Mandatory paid AI for routine work |
| Approval mode first; autonomous mode behind a threshold and cap | Unattended mass-applying |

## Architecture principles

1. **A modular monolith with enforced layers** (ADR-001). Imports only point down, and
   `tests/unit/test_architecture.py` fails the build otherwise.
2. **PostgreSQL is the only state store** (ADR-002). There is no Redis and no queue. The schema
   is reviewed SQL, and the migrations are frozen files.
3. **Short transactions** (ADR-003): one request is one transaction, repositories never
   commit, and no transaction stays open across a network or LLM call.
4. **Single user, local first** (ADR-004). There is no auth on loopback, and an API key
   otherwise.
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
- Strict TypeScript; types that mirror backend schemas live in `src/types/index.ts`.
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
  - `scripts/` holds `dev.sh`, `init_db.sh`, `smoke_backend.sh` and
    `validate_discovery.sh`.
  - `docs/` and `supabase/` hold supporting material.
- **Placeholders:** files marked `PLACEHOLDER - implemented in PHASE N` are stubs that the
  named phase replaces. Their names are intentions, not commitments.
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
careers URL. Application automation (Phase 7) will use the same three providers through
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

Revisit after Phase 7, starting with discovery only (see ADR-008).

## Future roadmap

| Phase | Content |
|---|---|
| 6 | Done: Agent 4 rule filtering; Agent 5 scoring (deterministic baseline, optional Claude for a shortlist); scores in the Jobs UI; Settings page (Claude Code command path still to do) |
| 7 | Done: application packages (Agents 6–9: tailored resume versions with change log, PDF/DOCX, cover letters, answers) with an approval workflow. Next: Agent 10 Playwright automation for Greenhouse/Lever/Ashby from approved packages, approval mode then autonomous mode with threshold and daily cap |
| MVP validation | Done: validated on a real resume and 5.4k real postings before automation (see `docs/MVP_VALIDATION.md`): parsing, relevance-ranked tailoring, specific and honest letters and answers, data lifecycle (ADR-013), faster scoring, expired jobs cannot be approved |
| 8 | Dashboard, applications, activity pages; learning insights (`learning/`) |
| 9 | Docker images, full compose, deployment and Supabase docs (personal deployment; real auth before anything public) |
| 10 | End-to-end tests (Playwright) in CI |
| Later | Workday discovery; more providers; full-text search; optional multi-user mode (Supabase Auth) |
