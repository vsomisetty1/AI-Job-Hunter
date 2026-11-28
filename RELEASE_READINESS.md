# Release readiness

**Version 0.10.0** (Phase 10, hardening and release readiness), 2026-11-28.

AI Job Hunter is a personal, single-user, local-only app. "Release" here means: safe and
dependable to run on your own machine for a real job search, in approval mode. It does not
mean a hosted or multi-user service.

**Verdict: ready for real use in approval mode (Phase 11). Not yet 1.0.** The engineering
gates below are met and verified by CI. The 1.0 gates that depend on real use (a real
submission on a live ATS, outcomes from real applications) and on browser tests through the
frontend are not met yet, by design: they are the next phases.

## 1. What is verified, and how

| Area | Evidence | Where |
|---|---|---|
| Backend logic | 650+ tests (unit, integration on real PostgreSQL 19, browser tests in real Chromium against mock Greenhouse/Lever/Ashby pages); no skips allowed; warnings are errors | CI `backend` job, `docs/TESTING.md` |
| Types and lint | `mypy --strict`, ruff incl. bandit security rules, format check | CI `backend` job |
| Frontend | 150 Vitest tests, strict typecheck, ESLint, production build | CI `frontend` job |
| Frontend/backend contract | Generated types from OpenAPI; compile-time checks of 68 response/request type pairs; every frontend API call matched to a backend operation; drift fails CI | `scripts/gen_api_contract.py`, `src/types/contract.ts`, `contract.test.ts`, `tests/unit/test_api_contract.py` |
| Real server | Migrates, starts `python -m app`, walks the main flows (resume upload to profile, discovery, scoring, package generate/approve/download, automation endpoints, outcomes, analytics, agent activity) | `scripts/smoke_backend.sh` |
| Containers | Both images build (backend with Chromium); stack starts healthy; ports on 127.0.0.1 only; non-root; Chromium fills a form inside the image | CI `docker` job, `scripts/smoke_compose.sh` |
| Security (local-only) | Foreign Host names refused (DNS rebinding); cross-site writes refused (CSRF) for every method and origin variant; security headers; config refuses unsafe combinations | `tests/unit/test_request_guard.py`, smoke tests |
| Approval mode only | API refuses autonomous settings; database refuses `AUTONOMOUS_MODE` in settings, applications and submissions; a submission needs `confirmed_at` | `test_settings_schema.py`, `test_foundation_api.py`, `test_migrations.py` |
| Backup and recovery | Every table and file restored byte for byte; corrupted and newer-schema backups refused; safety backup; retention; Compose volumes | `scripts/test_backup_restore.sh`, `scripts/smoke_compose.sh` |
| Dependencies | `pip-audit` and `npm audit`: no known vulnerabilities at release time | CI |
| Migrations | Upgrade and downgrade of every revision; catalog equals `schema.sql`; frozen SQL pinned by SHA-256 | `test_migrations.py`, `test_schema_sql.py` |
| Real-world checks (manual) | Discovery on live boards; packages from a real resume and 5.4k real postings; 6 live application forms filled in review mode | `docs/VALIDATION.md`, `docs/MVP_VALIDATION.md`, `docs/AUTOMATION_VALIDATION.md` |

Verified locally for this release as well (not only in CI): the full backend suite, mypy,
ruff, both audits, the frontend pipeline, the real-server smoke test, the backup round trip,
and the Compose stack with `scripts/smoke_compose.sh`. One exception: the backend image's
Chromium layer could not be built in the development sandbox (its network blocks the Debian
mirrors); the CI `docker` job builds and tests it.

## 2. Release checklist (0.10.0)

- [ ] CI green on every job (backend, frontend, scripts, docker): pending the first CI run of this commit; the Docker job (images with Chromium) has only run in CI
- [x] Version 0.10.0 in `backend/pyproject.toml`, `Settings.app_version`, `frontend/package.json` (a test keeps them equal)
- [x] Migration 0008 tested up and down; `schema.sql` matches
- [x] API contract regenerated and current
- [x] No placeholder files (`tests/unit/test_repository_hygiene.py`)
- [x] Docs consistent: README, PROJECT_STATE (single roadmap), AI_CONTEXT, TESTING, ADR index (001–016)
- [x] DEPLOYMENT.md, BACKUP_AND_RECOVERY.md, docs/SUPABASE_SETUP.md written
- [x] CHANGELOG.md entry

Before using it for real (owner):
- [ ] `cp .env.example .env`, strong `POSTGRES_PASSWORD`; if using Claude, an API key with a Console spend cap
- [ ] `docker compose up -d --build --wait`, open http://localhost:3000
- [ ] First backup, and a scheduled daily backup (BACKUP_AND_RECOVERY.md)
- [ ] Settings filled in (salary, work authorization, sponsorship, relocation): answers that need them are otherwise flagged for review

## 3. Known gaps and risks

| Risk | Impact | Mitigation now | Resolved by |
|---|---|---|---|
| **No submission has been made on a live ATS.** The submit click, confirmation detection and CAPTCHA-on-submit were tested only on mock pages. | A real submission could fail to be recognised (marked "unconfirmed") or need manual completion | Approval mode: you watch every submission; an unconfirmed one is never retried automatically and says to check your email | Phase 11 |
| No browser test through the real frontend and backend together | A UI regression that the component tests and contract miss | Contract checks, component tests, smoke tests | Phase 12 |
| Analytics endpoints return untyped JSON | Contract cannot catch drift there | Component tests with realistic data | Phase 12 |
| ATS sites change without notice | Form filling degrades for one platform | Fields found by meaning; failures reported with a reason; weekly live discovery check | Ongoing; Phase 11 feedback |
| Background work is in memory | A restart cancels running work | Startup marks it failed/cancelled; retry from the UI | Accepted (single user) |
| Backups are local files with personal data | Loss with the disk; exposure if copied carelessly | Mode 700, git-ignored; docs say to keep an encrypted off-machine copy | Owner |
| CAPTCHAs in the container | Cannot be solved headless | Run the backend natively with a visible browser for that application | Accepted |
| Static company directory | Suggestions drift | Empty-board notes in run details | After 1.0 |

Full lists: PROJECT_STATE.md §10 (technical debt) and §11 (limitations).

## 4. Gates for 1.0

| Gate | Status |
|---|---|
| Engineering: CI green incl. containers, contract, backups, security tests | Met (0.10.0) |
| Operations: documented deployment, backup and recovery, tested restore | Met (0.10.0) |
| Safety: approval mode enforced in API and database; local-only guard | Met (0.10.0) |
| Real use: at least 10 real confirmed submissions without a wrong or duplicate submission; outcomes recorded | Not met (Phase 11) |
| End-to-end: browser tests through frontend and backend in CI | Not met (Phase 12) |
| AI under the Pro plan: Claude Code commands for scoring, tailoring, letters via the API | Not met (Phase 13) |
| Release: version 1.0.0, changelog, tag | After the above |

Autonomous mode is **not** a 1.0 gate. It is blocked until a new ADR enables it, after
Phase 11 shows what converts.
