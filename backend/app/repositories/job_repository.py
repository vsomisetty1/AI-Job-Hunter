"""Job repository: set-based reads/writes for discovery, and job search."""

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import ColumnElement, Row, Select, and_, func, insert, or_, select, update
from sqlalchemy.orm import InstrumentedAttribute

from app.models.company import Company
from app.models.job import Job
from app.repositories.base import Repository
from app.schemas.job import JobSearchParams

# (Job, company name, source)
JobRow = Row[Job, str, str]

# Statuses a disappearing posting must not overwrite.
KEEP_ON_EXPIRY = ("expired", "applied")


class JobRepository(Repository[Job]):
    model = Job

    # ------------------------------------------------------ discovery reads
    async def existing_for_company(
        self, company_id: uuid.UUID
    ) -> dict[str, tuple[uuid.UUID, str | None, str]]:
        """source job id -> (job id, content hash, status)"""
        rows = await self.session.execute(
            select(Job.external_id, Job.id, Job.content_hash, Job.status).where(
                Job.company_id == company_id
            )
        )
        return {r.external_id: (r.id, r.content_hash, r.status) for r in rows}

    async def url_owners(self, urls: Sequence[str]) -> dict[str, tuple[uuid.UUID, str]]:
        if not urls:
            return {}
        rows = await self.session.execute(
            select(Job.url, Job.id, Job.external_id).where(Job.url.in_(list(urls)))
        )
        return {r.url: (r.id, r.external_id) for r in rows}

    async def fingerprint_owners(
        self, keys: Sequence[str], *, exclude_company: uuid.UUID
    ) -> dict[str, uuid.UUID]:
        if not keys:
            return {}
        rows = await self.session.execute(
            select(Job.dedup_key, Job.id)
            .where(
                Job.dedup_key.in_(list(keys)),
                Job.company_id != exclude_company,
                Job.status != "expired",
            )
            .order_by(Job.first_seen_at)
        )
        owners: dict[str, uuid.UUID] = {}
        for r in rows:
            owners.setdefault(r.dedup_key, r.id)
        return owners

    # ----------------------------------------------------- discovery writes
    async def insert_many(self, values: list[dict[str, Any]]) -> int:
        if not values:
            return 0
        await self.session.execute(insert(Job), values)
        return len(values)

    async def update_one(self, job_id: uuid.UUID, values: dict[str, Any]) -> None:
        await self.session.execute(update(Job).where(Job.id == job_id).values(**values))

    async def mark_seen(self, ids: Sequence[uuid.UUID], seen_at: datetime) -> None:
        if ids:
            await self.session.execute(
                update(Job).where(Job.id.in_(list(ids))).values(last_seen_at=seen_at)
            )

    async def expire_missing(self, company_id: uuid.UUID, crawl_started: datetime) -> int:
        """Postings not seen in this crawl are gone from the board."""
        result = await self.session.execute(
            update(Job)
            .where(
                Job.company_id == company_id,
                Job.last_seen_at < crawl_started,
                Job.status.not_in(KEEP_ON_EXPIRY),
            )
            .values(status="expired", expired_at=func.now())
        )
        return int(result.rowcount or 0)  # type: ignore[attr-defined]

    # --------------------------------------------------------------- search
    def _search_query(self, p: JobSearchParams) -> Select[Job, str, str]:
        stmt = select(Job, Company.name.label("company_name"), Company.source).join(Company)
        conditions = []
        if p.q:
            words = [w for w in p.q.split() if w][:8]
            for word in words:
                like = f"%{_escape_like(word)}%"
                conditions.append(
                    or_(
                        Job.title.ilike(like, escape="\\"),
                        Company.name.ilike(like, escape="\\"),
                        Job.location.ilike(like, escape="\\"),
                    )
                )
        if p.source:
            conditions.append(Company.source == p.source)
        if p.company_id:
            conditions.append(Job.company_id == p.company_id)
        if p.remote_type:
            conditions.append(Job.remote_type == p.remote_type)
        if p.status:
            conditions.append(Job.status == p.status)
        elif not p.include_expired:
            conditions.append(Job.status != "expired")
        return stmt.where(and_(*conditions)) if conditions else stmt

    async def search(self, p: JobSearchParams) -> tuple[list[JobRow], int]:
        base = self._search_query(p)
        total = await self.session.scalar(select(func.count()).select_from(base.subquery()))
        orders: dict[str, tuple[ColumnElement[Any] | InstrumentedAttribute[Any], ...]] = {
            "newest": (Job.first_seen_at.desc(), Job.id),
            "posted": (Job.posted_at.desc().nulls_last(), Job.id),
            "title": (Job.title, Job.id),
            "company": (Company.name, Job.title),
        }
        stmt = base.order_by(*orders[p.sort]).limit(p.limit).offset(p.offset)
        rows = await self.session.execute(stmt)
        return list(rows.all()), int(total or 0)

    async def get_with_company(self, job_id: uuid.UUID) -> JobRow | None:
        result = await self.session.execute(
            select(Job, Company.name.label("company_name"), Company.source)
            .join(Company)
            .where(Job.id == job_id)
        )
        return result.first()

    async def active_by_source(self) -> dict[str, int]:
        rows = await self.session.execute(
            select(Company.source, func.count())
            .select_from(Job)
            .join(Company)
            .where(Job.status != "expired")
            .group_by(Company.source)
        )
        return {source: int(n) for source, n in rows}

    async def stats(self) -> dict[str, dict[str, int]]:
        by: dict[str, dict[str, int]] = {"source": {}, "status": {}, "remote_type": {}}
        for key, column in (("source", Company.source), ("status", Job.status),
                            ("remote_type", Job.remote_type)):  # fmt: skip
            rows = await self.session.execute(
                select(column, func.count()).select_from(Job).join(Company).group_by(column)
            )
            by[key] = {str(value): int(n) for value, n in rows}
        return by


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
