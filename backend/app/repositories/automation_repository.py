"""Queries for application automation: submissions, their logs, the browser
sessions saved per platform, and the approved packages ready to automate."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import and_, delete, func, select, update

from app.models.application import Application
from app.models.application_package import ApplicationPackage
from app.models.application_submission import (
    ACTIVE_STATUSES,
    ApplicationSubmission,
    AutomationLog,
)
from app.models.browser_session import BrowserSession
from app.models.company import Company
from app.models.job import Job
from app.repositories.base import Repository


@dataclass(frozen=True)
class SubmissionRow:
    submission: ApplicationSubmission
    job_id: uuid.UUID
    job_title: str
    company_name: str
    job_status: str


@dataclass(frozen=True)
class ReadyRow:
    package: ApplicationPackage
    application_id: uuid.UUID
    job_title: str
    company_name: str
    platform: str
    job_status: str


class SubmissionRepository(Repository[ApplicationSubmission]):
    model = ApplicationSubmission

    async def lock(self, submission_id: uuid.UUID) -> ApplicationSubmission | None:
        return await self.session.get(ApplicationSubmission, submission_id, with_for_update=True)

    async def active_for(self, application_id: uuid.UUID) -> ApplicationSubmission | None:
        return await self.session.scalar(
            select(ApplicationSubmission).where(
                ApplicationSubmission.application_id == application_id,
                ApplicationSubmission.status.in_(ACTIVE_STATUSES),
            )
        )

    def _listing(self) -> Any:
        return (
            select(ApplicationSubmission, Job.id, Job.title, Company.name, Job.status)
            .join(Application, Application.id == ApplicationSubmission.application_id)
            .join(Job, Job.id == Application.job_id)
            .join(Company, Company.id == Job.company_id)
        )

    async def search(
        self, *, statuses: Sequence[str] | None, limit: int, offset: int
    ) -> tuple[list[SubmissionRow], int]:
        stmt = self._listing()
        count = select(func.count()).select_from(ApplicationSubmission)
        if statuses:
            stmt = stmt.where(ApplicationSubmission.status.in_(statuses))
            count = count.where(ApplicationSubmission.status.in_(statuses))
        rows = await self.session.execute(
            stmt.order_by(ApplicationSubmission.updated_at.desc()).limit(limit).offset(offset)
        )
        total = await self.session.scalar(count) or 0
        return [SubmissionRow(*r) for r in rows.all()], total

    async def get_row(self, submission_id: uuid.UUID) -> SubmissionRow | None:
        row = (
            await self.session.execute(
                self._listing().where(ApplicationSubmission.id == submission_id)
            )
        ).first()
        return SubmissionRow(*row) if row else None

    async def ids_in(self, statuses: Sequence[str]) -> list[uuid.UUID]:
        return list(
            await self.session.scalars(
                select(ApplicationSubmission.id).where(ApplicationSubmission.status.in_(statuses))
            )
        )

    async def interrupt(self, statuses: Sequence[str], message: str, now: datetime) -> int:
        result = await self.session.execute(
            update(ApplicationSubmission)
            .where(ApplicationSubmission.status.in_(statuses))
            .values(
                status="failed",
                error=message,
                error_kind="interrupted",
                failed_at=now,
                confirmed_at=None,
            )
        )
        return int(getattr(result, "rowcount", 0) or 0)

    async def ready_packages(self) -> list[ReadyRow]:
        """Approved packages whose application is ready and has no active or
        finished-with-success run."""
        busy = select(ApplicationSubmission.application_id).where(
            ApplicationSubmission.status.in_((*ACTIVE_STATUSES, "submitted"))
        )
        rows = await self.session.execute(
            select(
                ApplicationPackage,
                Application.id,
                Job.title,
                Company.name,
                Company.source,
                Job.status,
            )  # fmt: skip
            .join(Application, Application.id == ApplicationPackage.application_id)
            .join(Job, Job.id == ApplicationPackage.job_id)
            .join(Company, Company.id == Job.company_id)
            .where(
                ApplicationPackage.status == "approved",
                Application.status == "ready",
                Application.id.not_in(busy),
            )
            .order_by(ApplicationPackage.approved_at.desc())
        )
        return [ReadyRow(*r) for r in rows.all()]

    # ---------------------------------------------------------------- logs
    async def add_log(
        self,
        submission_id: uuid.UUID,
        level: str,
        step: str | None,
        message: str,
        detail: dict[str, Any],
    ) -> None:
        self.session.add(
            AutomationLog(
                submission_id=submission_id,
                level=level,
                step=step,
                message=message[:2000],
                detail=detail,
            )  # fmt: skip
        )

    async def logs(
        self,
        *,
        submission_id: uuid.UUID | None,
        levels: Sequence[str] | None,
        limit: int,
        offset: int,
    ) -> tuple[list[tuple[AutomationLog, str, str]], int]:
        conds = []
        if submission_id is not None:
            conds.append(AutomationLog.submission_id == submission_id)
        if levels:
            conds.append(AutomationLog.level.in_(levels))
        where = and_(*conds) if conds else None
        stmt = (
            select(AutomationLog, Job.title, Company.name)
            .join(ApplicationSubmission, ApplicationSubmission.id == AutomationLog.submission_id)
            .join(Application, Application.id == ApplicationSubmission.application_id)
            .join(Job, Job.id == Application.job_id)
            .join(Company, Company.id == Job.company_id)
        )
        count = select(func.count()).select_from(AutomationLog)
        if where is not None:
            stmt, count = stmt.where(where), count.where(where)
        rows = await self.session.execute(
            stmt.order_by(AutomationLog.created_at.desc(), AutomationLog.id)
            .limit(limit)
            .offset(offset)
        )
        return [(r[0], r[1], r[2]) for r in rows.all()], await self.session.scalar(count) or 0

    async def prune_logs(self, before: datetime) -> int:
        result = await self.session.execute(
            delete(AutomationLog).where(AutomationLog.created_at < before)
        )
        return int(getattr(result, "rowcount", 0) or 0)


class BrowserSessionRepository(Repository[BrowserSession]):
    model = BrowserSession

    async def state(self, platform: str, label: str = "default") -> dict[str, Any]:
        row = await self.session.scalar(
            select(BrowserSession).where(
                BrowserSession.platform == platform,
                BrowserSession.account_label == label,
                BrowserSession.is_valid.is_(True),
            )
        )
        return dict(row.storage_state) if row else {}

    async def save(
        self, platform: str, state: dict[str, Any], now: datetime, label: str = "default"
    ) -> None:
        row = await self.session.scalar(
            select(BrowserSession).where(
                BrowserSession.platform == platform, BrowserSession.account_label == label
            )
        )
        if row is None:
            row = BrowserSession(platform=platform, account_label=label)
            self.session.add(row)
        row.storage_state, row.is_valid, row.last_used_at = state, True, now
