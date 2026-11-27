# Architecture decision records

Each ADR records a decision that is already reflected in the code (as of 2026-11-27,
commit `e505d36`), why it was made, and what it costs. To change a decision, write a new
ADR that supersedes the old one; don't rewrite history.

| ADR | Decision |
|---|---|
| [001](ADR-001.md) | Modular monolith with enforced layers |
| [002](ADR-002.md) | PostgreSQL as the only datastore; frozen SQL migrations |
| [003](ADR-003.md) | Async SQLAlchemy with short, explicit units of work |
| [004](ADR-004.md) | Single-user, local-first security model |
| [005](ADR-005.md) | In-process scheduler and background tasks (one worker) |
| [006](ADR-006.md) | Deterministic first; Claude optional, cached, cost-tracked |
| [007](ADR-007.md) | Untrusted-document pipeline (validation + sandboxed extraction) |
| [008](ADR-008.md) | Public ATS APIs behind a connector interface; Workday deferred |
| [009](ADR-009.md) | Job identity, deduplication and lifecycle |
| [010](ADR-010.md) | Testing and CI strategy |
| [011](ADR-011.md) | Rule-based filtering and scoring, with optional Claude on a shortlist (Phase 6) |
| [012](ADR-012.md) | Application packages are built from facts and approved by a person (Phase 7) |
| [013](ADR-013.md) | Data lifecycle and storage cleanup (MVP validation) |
| [014](ADR-014.md) | Application automation in approval mode, by meaning, with checkpoints (Phase 8) |
| [015](ADR-015.md) | Learning from your own outcomes, with statistical gates (Phase 9) |
