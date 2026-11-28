"""Job repository: set-based reads/writes for discovery, and job search."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import (
    ColumnElement,
    Row,
    Select,
    and_,
    func,
    insert,
    or_,
    select,
    text,
    update,
)
from sqlalchemy.orm import InstrumentedAttribute

from app.models.candidate_profile import CandidateProfile
from app.models.company import Company
from app.models.job import Job
from app.repositories.base import Repository
from app.repositories.job_score_repository import (
    effective_method,
    effective_score,
    effective_score_join,
    passed_filters,
)
from app.schemas.job import JobSearchParams

# (Job, company name, source)
JobRow = Row[Job, str, str]
# (Job, company name, source, effective score, scoring method)
ScoredJobRow = Row[Job, str, str, int | None, str | None]

# Statuses the rule filter (re)evaluates; the others are user decisions or final.
FILTERABLE_STATUSES = ("new", "filtered", "scored")


@dataclass(frozen=True)
class FilterCandidate:
    id: uuid.UUID
    status: str
    title: str
    company_name: str
    location: str | None
    remote_type: str
    employment_type: str | None
    salary_min: int | None
    salary_max: int | None
    salary_currency: str | None
    description: str
    requirements: list[Any]
    duplicate_of: uuid.UUID | None
    filter_hash: str | None


# Cross-board duplicates among open jobs: for each fingerprint the earliest
# job is the original; jobs with that fingerprint at OTHER companies point to
# it. Same-company jobs with one fingerprint are distinct openings and stay.
# Expired jobs release their links. Returns one row per changed job.
_MARK_DUPLICATES = text(
    """
    WITH open_jobs AS (
        SELECT id, company_id, dedup_key, first_seen_at FROM jobs WHERE status <> 'expired'
    ),
    originals AS (
        SELECT DISTINCT ON (dedup_key) dedup_key, id AS original_id, company_id AS original_company
        FROM open_jobs ORDER BY dedup_key, first_seen_at, id
    ),
    desired AS (
        SELECT o.id,
               CASE WHEN o.company_id <> g.original_company THEN g.original_id END AS duplicate_of
        FROM open_jobs o JOIN originals g USING (dedup_key)
        UNION ALL
        SELECT id, NULL FROM jobs WHERE status = 'expired' AND duplicate_of IS NOT NULL
    )
    UPDATE jobs j SET duplicate_of = d.duplicate_of
    FROM desired d
    WHERE j.id = d.id AND j.duplicate_of IS DISTINCT FROM d.duplicate_of
    RETURNING j.duplicate_of IS NOT NULL AS is_duplicate
    """
)

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

    # ------------------------------------------------------- deduplication
    async def mark_cross_board_duplicates(self) -> dict[str, int]:
        rows = (await self.session.execute(_MARK_DUPLICATES)).all()
        marked = sum(1 for r in rows if r.is_duplicate)
        total_dupes = await self.session.scalar(
            select(func.count()).select_from(Job).where(Job.duplicate_of.is_not(None))
        )
        return {
            "marked": marked,
            "released": len(rows) - marked,
            "duplicates": int(total_dupes or 0),
        }

    # ----------------------------------------------------------- filtering
    async def filter_candidates(
        self, *, after: uuid.UUID | None, limit: int
    ) -> list[FilterCandidate]:
        stmt = (
            select(
                Job.id,
                Job.status,
                Job.title,
                Company.name,
                Job.location,
                Job.remote_type,
                Job.employment_type,
                Job.salary_min,
                Job.salary_max,
                Job.salary_currency,
                Job.description,
                Job.requirements,
                Job.duplicate_of,
                Job.filter_hash,
            )  # fmt: skip
            .join(Company, Company.id == Job.company_id)
            .where(Job.status.in_(FILTERABLE_STATUSES))
            .order_by(Job.id)
            .limit(limit)
        )
        if after is not None:
            stmt = stmt.where(Job.id > after)
        return [FilterCandidate(*tuple(r)) for r in await self.session.execute(stmt)]

    async def filter_counts(self) -> dict[str, int]:
        """Open jobs by filter state (expired jobs left out)."""
        open_job = Job.status != "expired"
        rejected = or_(Job.status == "filtered", Job.duplicate_of.is_not(None))
        row = (
            await self.session.execute(
                select(
                    func.count(),
                    func.count().filter(Job.filtered_at.is_(None)),
                    func.count().filter(passed_filters()),
                    func.count().filter(rejected),
                    func.count().filter(Job.duplicate_of.is_not(None)),
                ).where(open_job)
            )
        ).one()
        return dict(
            zip(
                ("active", "unfiltered", "passed", "rejected", "duplicate"),
                map(int, row),
                strict=True,
            )
        )

    async def apply_filter_results(self, rows: Sequence[dict[str, Any]]) -> None:
        """Bulk UPDATE by primary key; every dict has id, status, filter_* columns."""
        if rows:
            await self.session.execute(update(Job), list(rows))

    # --------------------------------------------------------------- search
    def _search_query(self, p: JobSearchParams) -> Select[Job, str, str, int | None, str | None]:
        active_profile = (
            select(CandidateProfile.id)
            .where(CandidateProfile.is_active.is_(True))
            .scalar_subquery()
        )
        score = effective_score()
        stmt = effective_score_join(
            select(
                Job,
                Company.name.label("company_name"),
                Company.source,
                score.label("score"),
                effective_method().label("score_method"),
            ).join(Company),
            active_profile,
        )
        conditions: list[ColumnElement[bool]] = []
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
        if p.filter_state == "passed":
            conditions.append(passed_filters())
        elif p.filter_state == "rejected":
            conditions.append(
                or_(
                    Job.filter_result["passed"].as_boolean().is_(False),
                    Job.duplicate_of.is_not(None),
                )
            )
        elif p.filter_state == "pending":
            conditions.append(Job.filtered_at.is_(None))
        if p.min_score is not None:
            conditions.append(score >= p.min_score)
        return stmt.where(and_(*conditions)) if conditions else stmt

    async def search(self, p: JobSearchParams) -> tuple[list[ScoredJobRow], int]:
        base = self._search_query(p)
        total = await self.session.scalar(select(func.count()).select_from(base.subquery()))
        score = effective_score()
        orders: dict[str, tuple[ColumnElement[Any] | InstrumentedAttribute[Any], ...]] = {
            "score": (score.desc().nulls_last(), Job.first_seen_at.desc(), Job.id),
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
