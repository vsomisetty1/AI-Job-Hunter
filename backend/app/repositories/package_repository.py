"""Application package repository: packages, their artifacts and answers."""

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import Row, func, select, update

from app.models.application import Application
from app.models.application_answer import ApplicationAnswer
from app.models.application_event import ApplicationEvent
from app.models.application_package import LIVE_STATUSES, ApplicationPackage
from app.models.company import Company
from app.models.cover_letter import CoverLetter
from app.models.job import Job
from app.repositories.base import Repository

# (package, job title, company name, answers needing review)
PackageRow = Row[ApplicationPackage, str, str, int]


class PackageRepository(Repository[ApplicationPackage]):
    model = ApplicationPackage

    async def lock(self, package_id: uuid.UUID) -> ApplicationPackage | None:
        return await self.session.scalar(
            select(ApplicationPackage).where(ApplicationPackage.id == package_id).with_for_update()
        )

    async def live(self, job_id: uuid.UUID, profile_id: uuid.UUID) -> ApplicationPackage | None:
        return await self.session.scalar(
            select(ApplicationPackage)
            .where(
                ApplicationPackage.job_id == job_id,
                ApplicationPackage.profile_id == profile_id,
                ApplicationPackage.status.in_(LIVE_STATUSES),
            )
            .with_for_update()
        )

    async def next_version(self, job_id: uuid.UUID, profile_id: uuid.UUID) -> int:
        current = await self.session.scalar(
            select(func.max(ApplicationPackage.version_number)).where(
                ApplicationPackage.job_id == job_id, ApplicationPackage.profile_id == profile_id
            )
        )
        return int(current or 0) + 1

    def _listing(self) -> Any:
        review = (
            select(func.count())
            .where(
                ApplicationAnswer.package_id == ApplicationPackage.id,
                ApplicationAnswer.needs_review.is_(True),
            )
            .correlate(ApplicationPackage)
            .scalar_subquery()
        )
        return (
            select(ApplicationPackage, Job.title, Company.name, review.label("needs_review"))
            .join(Job, Job.id == ApplicationPackage.job_id)
            .join(Company, Company.id == Job.company_id)
        )

    async def search(
        self,
        *,
        statuses: Sequence[str] | None,
        job_id: uuid.UUID | None,
        limit: int,
        offset: int,
    ) -> tuple[list[PackageRow], int]:
        stmt = self._listing()
        if statuses:
            stmt = stmt.where(ApplicationPackage.status.in_(list(statuses)))
        if job_id:
            stmt = stmt.where(ApplicationPackage.job_id == job_id)
        total = await self.session.scalar(select(func.count()).select_from(stmt.subquery()))
        rows = await self.session.execute(
            stmt.order_by(ApplicationPackage.created_at.desc(), ApplicationPackage.id)
            .limit(limit)
            .offset(offset)
        )
        return list(rows.all()), int(total or 0)

    async def get_row(self, package_id: uuid.UUID) -> PackageRow | None:
        result = await self.session.execute(
            self._listing().where(ApplicationPackage.id == package_id)
        )
        return result.first()

    async def answers(self, package_id: uuid.UUID) -> list[ApplicationAnswer]:
        rows = await self.session.scalars(
            select(ApplicationAnswer)
            .where(ApplicationAnswer.package_id == package_id)
            .order_by(ApplicationAnswer.created_at, ApplicationAnswer.question_key)
        )
        return list(rows)

    async def answer(self, package_id: uuid.UUID, answer_id: uuid.UUID) -> ApplicationAnswer | None:
        return await self.session.scalar(
            select(ApplicationAnswer).where(
                ApplicationAnswer.id == answer_id, ApplicationAnswer.package_id == package_id
            )
        )

    async def add_answers(self, rows: Sequence[dict[str, Any]]) -> None:
        for row in rows:
            self.session.add(ApplicationAnswer(**row))
        await self.session.flush()

    async def next_cover_letter_version(self, job_id: uuid.UUID, profile_id: uuid.UUID) -> int:
        current = await self.session.scalar(
            select(func.max(CoverLetter.version_number)).where(
                CoverLetter.job_id == job_id, CoverLetter.profile_id == profile_id
            )
        )
        return int(current or 0) + 1

    async def mark_interrupted(self, message: str) -> int:
        result = await self.session.execute(
            update(ApplicationPackage)
            .where(ApplicationPackage.status == "generating")
            .values(status="failed", error=message)
        )
        return int(result.rowcount or 0)  # type: ignore[attr-defined]

    # ------------------------------------------------------- applications
    async def application_for(self, job_id: uuid.UUID, profile_id: uuid.UUID) -> Application | None:
        return await self.session.scalar(
            select(Application)
            .where(Application.job_id == job_id, Application.profile_id == profile_id)
            .with_for_update()
        )

    async def add_event(self, application_id: uuid.UUID, **values: Any) -> None:
        self.session.add(ApplicationEvent(application_id=application_id, **values))
        await self.session.flush()
