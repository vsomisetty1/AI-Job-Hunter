"""Company (job board) repository."""

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import case, func, select

from app.models.company import Company
from app.models.job import Job
from app.repositories.base import Repository


class CompanyRepository(Repository[Company]):
    model = Company

    async def get_by_board(self, source: str, slug: str) -> Company | None:
        return await self.session.scalar(
            select(Company).where(Company.source == source, Company.slug == slug)
        )

    async def list_with_counts(self) -> list[tuple[Company, int]]:
        active = func.count(Job.id).filter(Job.status != "expired")
        rows = await self.session.execute(
            select(Company, active)
            .outerjoin(Job, Job.company_id == Company.id)
            .group_by(Company.id)
            .order_by(Company.is_tracked.desc(), func.lower(Company.name))
        )
        return [(c, int(n)) for c, n in rows.all()]

    async def for_crawl(
        self, *, ids: Sequence[uuid.UUID] | None = None, due_before: datetime | None = None
    ) -> Sequence[Company]:
        """Tracked companies to crawl: never-crawled first, then the oldest crawl."""
        stmt = select(Company).where(Company.is_tracked.is_(True))
        if ids:
            stmt = select(Company).where(Company.id.in_(list(ids)))
        if due_before is not None:
            stmt = stmt.where(
                (Company.last_crawled_at.is_(None)) | (Company.last_crawled_at < due_before)
            )
        stmt = stmt.order_by(Company.last_crawled_at.asc().nulls_first())
        return (await self.session.scalars(stmt)).all()

    async def first_tracked_slug(self, source: str) -> str | None:
        return await self.session.scalar(
            select(Company.slug)
            .where(Company.source == source, Company.is_tracked.is_(True))
            .order_by((Company.last_crawl_status == "ok").desc(), Company.created_at)
            .limit(1)
        )

    async def has_jobs(self, company_id: uuid.UUID) -> bool:
        return bool(
            await self.session.scalar(select(func.count()).where(Job.company_id == company_id))
        )

    async def source_health(self) -> dict[str, dict[str, Any]]:
        failing = case((Company.consecutive_failures > 0, 1), else_=0)
        rows = await self.session.execute(
            select(
                Company.source,
                func.count().filter(Company.is_tracked.is_(True)),
                func.sum(failing).filter(Company.is_tracked.is_(True)),
                func.max(Company.last_crawled_at).filter(Company.last_crawl_status == "ok"),
            ).group_by(Company.source)
        )
        return {
            source: {
                "companies_tracked": int(tracked or 0),
                "companies_failing": int(fails or 0),
                "last_success_at": last_ok,
            }
            for source, tracked, fails, last_ok in rows
        }
