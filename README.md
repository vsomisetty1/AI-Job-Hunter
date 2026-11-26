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
| 2 | Database (schema, migrations, ORM) | Pending |
| 3 | Backend foundation | Pending |
| 4 | Resume system (Agents 0, 1, 6, 7, 8) | Pending |
| 5 | Job discovery (Agents 2, 3, 4) | Pending |
| 6 | Scoring + learning (Agent 5) | Pending |
| 7 | Application automation (Agents 9, 10) | Pending |
| 8 | Frontend | Pending |
| 9 | Deployment | Pending |
| 10 | Testing | Pending |

Files containing `PLACEHOLDER - implemented in PHASE N` are stubs filled in by that phase.
