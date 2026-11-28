# Changelog

Versions follow the project phases until 1.0 (see PROJECT_STATE.md §13).

## 0.10.0 (2026-11-28): hardening and release readiness

### Security
- Local request guard (ADR-016): requests for host names outside `ALLOWED_HOSTS` are
  refused (DNS rebinding); state-changing requests from other web origins are refused
  (CSRF); every page and API response forbids framing and MIME sniffing.
- Approval mode only: the settings API refuses `application_mode`, `auto_apply_threshold`
  and `daily_application_cap`; migration 0008 makes the database refuse `AUTONOMOUS_MODE`
  in settings and applications.

### Added
- Docker images for the backend (with headless Chromium) and frontend, and a full Compose
  stack, loopback only, non-root (DEPLOYMENT.md).
- `scripts/backup.sh` and `scripts/restore.sh` with checksums, schema-revision checks and a
  safety backup (BACKUP_AND_RECOVERY.md).
- Agent activity: `GET /api/v1/agent-runs`, `/summary`, `/agents` and the `/activity` page.
- Frontend/backend API contract generated from OpenAPI and checked in CI.
- CI: backup round trip, shellcheck, Docker build and Compose smoke test.
- RELEASE_READINESS.md, DEPLOYMENT.md, BACKUP_AND_RECOVERY.md, docs/SUPABASE_SETUP.md, ADR-016.

### Changed
- API responses state exact values: job and company `source`, crawl and inference statuses,
  resume version `source`, timeline event `status`; discovery run details, answer evidence
  and editable form fields are typed objects.
- The settings API no longer returns `auto_apply_threshold` or `daily_application_cap`.
- A relative `LOCAL_STORAGE_DIR` is resolved against `backend/` regardless of the working
  directory.
- `package_service` split into `package_generator`, `package_workflow`, `package_inputs`;
  `automation_service` split into `automation_service`, `automation_facts`,
  `automation_recorder`, `automation_views`.

### Fixed
- The profile editor could send a seniority value the API rejects.
- The Supabase bucket refused automation screenshots (PNG); re-run `supabase/storage.sql`.

### Removed
- Placeholder modules, pages and documents; unused `PLAYWRIGHT_HEADLESS` and
  `BROWSER_STATE_DIR` settings; the frontend's unused `@playwright/test`.

## 0.9.0 and earlier

Phases 1–9: see the "Completed phases" table in PROJECT_STATE.md.
