"""Queries for outcome tracking: the application pipeline, interview events
and the rows an outcome timeline is built from."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select

from app.models.application import Application
from app.models.application_package import ApplicationPackage
from app.models.company import Company
from app.models.job import Job
from app.models.learning import InterviewEvent
from app.repositories.base import Repository

SENT_STATUSES = ("submitted", "interview", "rejected", "offer", "withdrawn")


@dataclass(frozen=True)
class PipelineRow:
    application: Application
    job: Job
    company: Company
    package_id: uuid.UUID | None


@dataclass(frozen=True)
class PackageMilestone:
    package_id: uuid.UUID
    job_id: uuid.UUID
    application_id: uuid.UUID | None
    version: int
    generated_at: datetime | None
    approved_at: datetime | None
    job_title: str
    company_name: str


class OutcomeRepository(Repository[InterviewEvent]):
    model = InterviewEvent

    async def pipeline(
        self,
        *,
        statuses: Sequence[str] | None = None,
        application_ids: Sequence[uuid.UUID] | None = None,
    ) -> list[PipelineRow]:
        latest_package = (
            select(ApplicationPackage.id)
            .where(ApplicationPackage.application_id == Application.id)
            .order_by(ApplicationPackage.version_number.desc())
            .limit(1)
            .scalar_subquery()
        )
        stmt = (
            select(Application, Job, Company, latest_package)
            .join(Job, Job.id == Application.job_id)
            .join(Company, Company.id == Job.company_id)
            .where(Application.status.in_(statuses or SENT_STATUSES))
            .order_by(Application.submitted_at.desc().nulls_last())
        )
        if application_ids is not None:
            stmt = stmt.where(Application.id.in_(application_ids))
        rows = await self.session.execute(stmt)
        return [PipelineRow(*r) for r in rows.all()]

    async def events_for(self, application_ids: Sequence[uuid.UUID]) -> list[InterviewEvent]:
        if not application_ids:
            return []
        return list(
            await self.session.scalars(
                select(InterviewEvent)
                .where(InterviewEvent.application_id.in_(application_ids))
                .order_by(InterviewEvent.occurred_at, InterviewEvent.created_at)
            )
        )

    async def event(self, application_id: uuid.UUID, event_id: uuid.UUID) -> InterviewEvent | None:
        return await self.session.scalar(
            select(InterviewEvent).where(
                InterviewEvent.id == event_id, InterviewEvent.application_id == application_id
            )
        )

    async def package_milestones(
        self, application_ids: Sequence[uuid.UUID] | None = None, limit: int = 1000
    ) -> list[PackageMilestone]:
        stmt = (
            select(
                ApplicationPackage.id,
                ApplicationPackage.job_id,
                ApplicationPackage.application_id,
                ApplicationPackage.version_number,
                ApplicationPackage.generated_at,
                ApplicationPackage.approved_at,
                Job.title,
                Company.name,
            )  # fmt: skip
            .join(Job, Job.id == ApplicationPackage.job_id)
            .join(Company, Company.id == Job.company_id)
            .where(ApplicationPackage.generated_at.is_not(None))
            .order_by(ApplicationPackage.generated_at.desc())
            .limit(limit)
        )
        if application_ids is not None:
            stmt = stmt.where(ApplicationPackage.application_id.in_(application_ids))
        return [PackageMilestone(*r) for r in (await self.session.execute(stmt)).all()]

    async def event_counts(self) -> dict[str, int]:
        rows = await self.session.execute(
            select(InterviewEvent.stage, func.count()).group_by(InterviewEvent.stage)
        )
        return {str(stage): int(n) for stage, n in rows.all()}
