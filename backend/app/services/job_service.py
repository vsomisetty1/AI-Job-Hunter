"""Job queries for the API (search, detail, raw payload, stats)."""

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.job import Job
from app.repositories.candidate_profile_repository import CandidateProfileRepository
from app.repositories.job_repository import JobRepository, JobRow
from app.repositories.job_score_repository import JobScoreRepository
from app.schemas.common import Page
from app.schemas.job import JobDetail, JobSearchParams, JobSummary
from app.schemas.job_score import FilterResult, JobScoreRead

_COMPUTED = {"company_name", "source", "score", "score_method", "scores", "filter_result"}
_SUMMARY_FIELDS = tuple(f for f in JobSummary.model_fields if f not in _COMPUTED)
_DETAIL_FIELDS = tuple(f for f in JobDetail.model_fields if f not in _COMPUTED)


def _filter_result(job: Job) -> FilterResult | None:
    return FilterResult.model_validate(job.filter_result) if job.filter_result else None


class JobService:
    def __init__(self, session: AsyncSession) -> None:
        self.repo = JobRepository(session)
        self.scores = JobScoreRepository(session)
        self.profiles = CandidateProfileRepository(session)

    async def search(self, params: JobSearchParams) -> Page[JobSummary]:
        rows, total = await self.repo.search(params)
        items = [
            JobSummary(
                **{f: getattr(job, f) for f in _SUMMARY_FIELDS},
                company_name=company_name,
                source=source,
                score=score,
                score_method=method,
            )
            for job, company_name, source, score, method in rows
        ]
        return Page[JobSummary](items=items, total=total, limit=params.limit, offset=params.offset)

    async def detail(self, job_id: uuid.UUID) -> JobDetail:
        job, company_name, source = await self._row(job_id)
        profile = await self.profiles.get_active()
        rows = await self.scores.for_job(job_id, profile.id) if profile else []
        rules = next((r for r in rows if r.scoring_method == "rules"), None)
        # A Claude score counts only while it was computed from the current inputs.
        claude = next(
            (
                r
                for r in rows
                if r.scoring_method == "claude"
                and rules is not None
                and r.input_hash == rules.input_hash
            ),
            None,
        )
        current = claude or rules
        scores = [
            JobScoreRead.model_validate(r).model_copy(
                update={"is_current": r is rules or r is claude}
            )
            for r in sorted(rows, key=lambda r: r.scoring_method != "rules")
        ]
        return JobDetail(
            **{f: getattr(job, f) for f in _DETAIL_FIELDS},
            company_name=company_name,
            source=source,
            score=current.overall_score if current else None,
            score_method=current.scoring_method if current else None,
            filter_result=_filter_result(job),
            scores=scores,
        )

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
