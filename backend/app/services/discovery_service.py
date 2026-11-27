"""Discovery: crawl tracked company boards, deduplicate, store, monitor.

One run = one `discovery_runs` row (at most one running). For each company:

1. fetch + normalize + validate the board (network, no transaction open)
2. in ONE short transaction: deduplicate against stored jobs, insert new
   postings, update changed ones, mark all seen ones (`last_seen_at`),
   revive postings that came back, expire postings that disappeared, and
   record the company's crawl status.

Companies are crawled concurrently (DISCOVERY_CONCURRENCY); one company's
failure never stops the others. Scheduled runs only crawl companies that are
due (incremental refresh); manual runs crawl every tracked company, or the
ones requested.
"""

import asyncio
import logging
import time
import uuid
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import status
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.agent_2_job_discovery import BoardResult, fetch_board
from app.agents.agent_3_deduplication import Existing, decide, dedup_key
from app.agents.runs import track_agent_run
from app.connectors.base import Connector, ConnectorHealth
from app.core.config import Settings
from app.core.exceptions import AppError, NotFoundError
from app.models.company import Company
from app.models.discovery_run import DiscoveryRun
from app.repositories.company_repository import CompanyRepository
from app.repositories.job_repository import JobRepository
from app.services.job_normalizer import insert_values, update_values

logger = logging.getLogger(__name__)

MAX_ERROR_CHARS = 1000


class DiscoveryInProgressError(AppError):
    status_code = status.HTTP_409_CONFLICT
    code = "discovery_in_progress"


@dataclass
class CompanyOutcome:
    company_id: str
    source: str
    slug: str
    name: str
    status: str = "ok"  # ok | error | not_found
    found: int = 0
    invalid: int = 0
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    skipped: int = 0
    expired: int = 0
    pages: int = 0
    duration_ms: int = 0
    error: str | None = None
    notes: list[str] = field(default_factory=list)
    skip_reasons: dict[str, int] = field(default_factory=dict)
    invalid_samples: list[dict[str, object]] = field(default_factory=list)


@dataclass(frozen=True)
class _Target:
    id: uuid.UUID
    source: str
    slug: str
    name: str


class DiscoveryService:
    def __init__(
        self,
        settings: Settings,
        connectors: dict[str, Connector],
        sessionmaker: async_sessionmaker[AsyncSession],
    ) -> None:
        self.settings = settings
        self.connectors = connectors
        self.sessionmaker = sessionmaker

    # -------------------------------------------------------------- runs
    async def start(self, trigger: str) -> uuid.UUID:
        """Create the run row; refuses while another run is in progress."""
        try:
            async with self.sessionmaker() as session, session.begin():
                run = DiscoveryRun(trigger=trigger)
                session.add(run)
                await session.flush()
                return run.id
        except IntegrityError as exc:
            if "uq_discovery_runs_one_running" in str(exc.orig):
                raise DiscoveryInProgressError("A discovery run is already in progress.") from exc
            raise

    async def run(
        self,
        trigger: str,
        *,
        company_ids: list[uuid.UUID] | None = None,
        only_due: bool = False,
    ) -> dict[str, Any]:
        run_id = await self.start(trigger)
        return await self.execute(run_id, company_ids=company_ids, only_due=only_due)

    async def execute(
        self,
        run_id: uuid.UUID,
        *,
        company_ids: list[uuid.UUID] | None = None,
        only_due: bool = False,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        try:
            async with track_agent_run(
                "agent_2_job_discovery",
                input_summary={
                    "run_id": str(run_id),
                    "only_due": only_due,
                    "company_ids": [str(c) for c in company_ids or []],
                },  # fmt: skip
                sessionmaker=self.sessionmaker,
            ) as agent_run:
                targets = await self._targets(company_ids, only_due)
                outcomes = await self._crawl_all(targets)
                summary = self._summarize(outcomes)
                agent_run.output_summary = {k: v for k, v in summary.items() if k != "details"}
        except Exception as exc:
            await self._finish(run_id, None, started, error=f"{type(exc).__name__}: {exc}")
            raise
        run_status = await self._finish(run_id, summary, started)
        return {"run_id": str(run_id), "status": run_status} | summary

    async def _targets(self, company_ids: list[uuid.UUID] | None, only_due: bool) -> list[_Target]:
        due_before = None
        if only_due and not company_ids:
            # 10% slack so a company crawled slightly late is not skipped a whole cycle.
            due_before = datetime.now(UTC) - timedelta(
                minutes=self.settings.discovery_interval_minutes * 0.9
            )
        async with self.sessionmaker() as session:
            companies = await CompanyRepository(session).for_crawl(
                ids=company_ids, due_before=due_before
            )
            return [_Target(c.id, c.source, c.slug, c.name) for c in companies]

    async def _crawl_all(self, targets: list[_Target]) -> list[CompanyOutcome]:
        limit = asyncio.Semaphore(self.settings.discovery_concurrency)

        async def one(target: _Target) -> CompanyOutcome:
            async with limit:
                try:
                    return await self.crawl_company(target)
                except Exception as exc:
                    logger.exception("discovery crashed for %s/%s", target.source, target.slug)
                    outcome = CompanyOutcome(
                        str(target.id), target.source, target.slug, target.name
                    )
                    outcome.status, outcome.error = "error", f"{type(exc).__name__}: {exc}"
                    await self._record_company(target.id, outcome)
                    return outcome

        return list(await asyncio.gather(*(one(t) for t in targets)))

    # ----------------------------------------------------------- company
    async def crawl_company(self, target: _Target) -> CompanyOutcome:
        outcome = CompanyOutcome(str(target.id), target.source, target.slug, target.name)
        connector = self.connectors.get(target.source)
        if connector is None:
            outcome.status, outcome.error = "error", f"no connector for source {target.source!r}"
            await self._record_company(target.id, outcome)
            return outcome

        result = await fetch_board(connector, target.slug)
        outcome.duration_ms, outcome.pages, outcome.notes = (
            result.duration_ms, result.pages, list(result.notes),
        )  # fmt: skip
        if not result.ok:
            outcome.status = "not_found" if result.not_found else "error"
            outcome.error = (result.error or "unknown error")[:MAX_ERROR_CHARS]
            await self._record_company(target.id, outcome)
            return outcome

        outcome.found, outcome.invalid = result.found, result.invalid_count
        outcome.invalid_samples = result.invalid
        await self._persist(target, result, outcome)
        return outcome

    async def _persist(self, target: _Target, result: BoardResult, outcome: CompanyOutcome) -> None:
        seen_at = datetime.now(UTC)
        async with self.sessionmaker() as session, session.begin():
            jobs = JobRepository(session)
            existing = {
                ext: Existing(*row)
                for ext, row in (await jobs.existing_for_company(target.id)).items()
            }
            urls = [j.url for j in result.jobs]
            keys = [dedup_key(j.company_name, j.title, j.location) for j in result.jobs]
            decisions = decide(
                result.jobs,
                existing=existing,
                url_owners=await jobs.url_owners(urls),
                fingerprint_owners=await jobs.fingerprint_owners(keys, exclude_company=target.id),
            )
            inserts, seen_ids, reasons = [], [], Counter[str]()
            for d in decisions:
                if d.action == "insert":
                    inserts.append(insert_values(d.job, target.id, seen_at))
                elif d.action == "update" and d.existing_id:
                    await jobs.update_one(
                        d.existing_id, update_values(d.job, seen_at, revive=d.revive)
                    )
                elif d.action == "unchanged" and d.existing_id:
                    seen_ids.append(d.existing_id)
                elif d.action == "skip":
                    reasons[d.reason or "skipped"] += 1
            await jobs.insert_many(inserts)
            await jobs.mark_seen(seen_ids, seen_at)
            # Only a complete board response proves a posting is gone.
            expired = await jobs.expire_missing(target.id, seen_at) if result.complete else 0

            counts = Counter(d.action for d in decisions)
            outcome.inserted, outcome.updated = counts["insert"], counts["update"]
            outcome.unchanged, outcome.skipped = counts["unchanged"], counts["skip"]
            outcome.expired, outcome.skip_reasons = expired, dict(reasons)
            if not result.complete:
                outcome.notes.append("response looked incomplete: nothing was expired")
            await self._update_company(session, target.id, outcome)
        logger.info(
            "discovered %s/%s: %s found, %s new, %s updated, %s expired",
            target.source, target.slug, outcome.found, outcome.inserted, outcome.updated,
            outcome.expired,
        )  # fmt: skip

    async def _record_company(self, company_id: uuid.UUID, outcome: CompanyOutcome) -> None:
        async with self.sessionmaker() as session, session.begin():
            await self._update_company(session, company_id, outcome)

    @staticmethod
    async def _update_company(
        session: AsyncSession, company_id: uuid.UUID, outcome: CompanyOutcome
    ) -> None:
        ok = outcome.status == "ok"
        await session.execute(
            update(Company)
            .where(Company.id == company_id)
            .values(
                last_crawled_at=func.now(),
                last_crawl_status=outcome.status,
                last_error=None if ok else outcome.error,
                consecutive_failures=0 if ok else Company.consecutive_failures + 1,
            )
        )

    # --------------------------------------------------------- summaries
    @staticmethod
    def _summarize(outcomes: list[CompanyOutcome]) -> dict[str, Any]:
        failed = [o for o in outcomes if o.status != "ok"]
        return {
            "companies_total": len(outcomes),
            "companies_succeeded": len(outcomes) - len(failed),
            "companies_failed": len(failed),
            "jobs_found": sum(o.found for o in outcomes),
            "jobs_inserted": sum(o.inserted for o in outcomes),
            "jobs_updated": sum(o.updated for o in outcomes),
            "jobs_unchanged": sum(o.unchanged for o in outcomes),
            "jobs_skipped": sum(o.skipped + o.invalid for o in outcomes),
            "jobs_expired": sum(o.expired for o in outcomes),
            "details": [asdict(o) for o in outcomes],
        }

    async def _finish(
        self,
        run_id: uuid.UUID,
        summary: dict[str, Any] | None,
        started: float,
        error: str | None = None,
    ) -> str:
        if summary is None:
            run_status = "failed"
            values: dict[str, Any] = {}
        else:
            total, failed = summary["companies_total"], summary["companies_failed"]
            run_status = "succeeded" if failed == 0 else "failed" if failed == total else "partial"
            values = dict(summary)
            if failed:
                error = f"{failed} of {total} companies failed"
        async with self.sessionmaker() as session, session.begin():
            await session.execute(
                update(DiscoveryRun)
                .where(DiscoveryRun.id == run_id)
                .values(
                    **values,
                    status=run_status,
                    error=(error or None) and error[:MAX_ERROR_CHARS],
                    finished_at=func.clock_timestamp(),
                    duration_ms=int((time.perf_counter() - started) * 1000),
                )
            )
        return run_status

    # ----------------------------------------------------------- health
    async def health(self, *, probe: bool) -> list[dict[str, Any]]:
        async with self.sessionmaker() as session:
            per_source = await CompanyRepository(session).source_health()
            jobs_by_source = await JobRepository(session).active_by_source()
            probe_boards = {
                source: await CompanyRepository(session).first_tracked_slug(source)
                for source in self.connectors
            }
        probes: dict[str, ConnectorHealth] = {}
        if probe:
            results = await asyncio.gather(
                *(c.health_check(probe_boards.get(s)) for s, c in self.connectors.items())
            )
            probes = {h.source: h for h in results}
        out = []
        for source, connector in self.connectors.items():
            stats = per_source.get(source, {"companies_tracked": 0, "companies_failing": 0,
                                            "last_success_at": None})  # fmt: skip
            out.append(
                {
                    "source": source,
                    "display_name": connector.display_name,
                    **stats,
                    "jobs_active": jobs_by_source.get(source, 0),
                    "probe": asdict(probes[source]) if source in probes else None,
                }
            )
        return out

    async def recent_runs(self, *, limit: int, offset: int) -> tuple[list[DiscoveryRun], int]:
        async with self.sessionmaker() as session:
            total = await session.scalar(select(func.count()).select_from(DiscoveryRun)) or 0
            runs = await session.scalars(
                select(DiscoveryRun)
                .order_by(DiscoveryRun.started_at.desc())
                .limit(limit)
                .offset(offset)
            )
            return list(runs), int(total)

    async def get_run(self, run_id: uuid.UUID) -> DiscoveryRun:
        async with self.sessionmaker() as session:
            run = await session.get(DiscoveryRun, run_id)
            if run is None:
                raise NotFoundError("Discovery run not found", {"run_id": str(run_id)})
            return run
