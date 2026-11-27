"""Job queries for the API (search, detail, raw payload, stats)."""

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.repositories.job_repository import JobRepository, JobRow
from app.schemas.common import Page
from app.schemas.job import JobDetail, JobSearchParams, JobSummary

_SUMMARY_FIELDS = tuple(f for f in JobSummary.model_fields if f not in {"company_name", "source"})
_DETAIL_FIELDS = tuple(f for f in JobDetail.model_fields if f not in {"company_name", "source"})


def _summary(row: JobRow) -> JobSummary:
    job, company_name, source = row
    return JobSummary(
        **{f: getattr(job, f) for f in _SUMMARY_FIELDS}, company_name=company_name, source=source
    )


def _detail(row: JobRow) -> JobDetail:
    job, company_name, source = row
    return JobDetail(
        **{f: getattr(job, f) for f in _DETAIL_FIELDS}, company_name=company_name, source=source
    )


class JobService:
    def __init__(self, session: AsyncSession) -> None:
        self.repo = JobRepository(session)

    async def search(self, params: JobSearchParams) -> Page[JobSummary]:
        rows, total = await self.repo.search(params)
        return Page[JobSummary](
            items=[_summary(r) for r in rows], total=total, limit=params.limit, offset=params.offset
        )

    async def detail(self, job_id: uuid.UUID) -> JobDetail:
        return _detail(await self._row(job_id))

    async def raw(self, job_id: uuid.UUID) -> dict[str, Any]:
        job, _, source = await self._row(job_id)
        return {"source": source, "external_id": job.external_id, "raw": job.raw or {}}

    async def stats(self) -> dict[str, dict[str, int]]:
        return await self.repo.stats()

    async def _row(self, job_id: uuid.UUID) -> JobRow:
        row = await self.repo.get_with_company(job_id)
        if row is None:
            raise NotFoundError("Job not found", {"job_id": str(job_id)})
        return row
