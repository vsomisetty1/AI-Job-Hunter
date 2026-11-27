"""Interview and outcome tracking.

You record what happened after applying: a recruiter response, screens and
interview rounds (scheduled, completed, cancelled, no-show), an offer, a
rejection or a withdrawal. The application's milestones (`responded_at`,
`first_interview_at`, `offer_at`, `rejected_at`, `withdrawn_at`) and its status
are always DERIVED from those events, so editing or deleting an event keeps
everything consistent. Package generation and approval and the submission
come from their own rows; together they form the outcome timeline.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, DomainValidationError, NotFoundError
from app.models.application import Application
from app.models.learning import INTERVIEW_ROUNDS, INTERVIEW_STAGES, InterviewEvent
from app.repositories.outcome_repository import OutcomeRepository, PipelineRow
from app.repositories.package_repository import PackageRepository
from app.schemas.outcomes import (
    ApplicationOutcomes,
    InterviewEventCreate,
    InterviewEventRead,
    InterviewEventUpdate,
    PipelineItem,
    TimelineEntry,
)

ALWAYS_COMPLETED = ("recruiter_response", "offer", "rejection", "withdrawal")
FUTURE_TOLERANCE = timedelta(hours=1)
STAGE_LABEL = {
    "recruiter_response": "Recruiter response",
    "recruiter_screen": "Recruiter screen",
    "phone_screen": "Phone screen",
    "technical_interview": "Technical interview",
    "hiring_manager_interview": "Hiring manager interview",
    "onsite": "Onsite",
    "final_round": "Final round",
    "offer": "Offer",
    "rejection": "Rejection",
    "withdrawal": "Withdrawn",
}
_TERMINAL_STATUS = {"offer": "offer", "rejection": "rejected", "withdrawal": "withdrawn"}


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class Milestones:
    responded_at: datetime | None
    first_interview_at: datetime | None
    offer_at: datetime | None
    rejected_at: datetime | None
    withdrawn_at: datetime | None
    status: str  # submitted, interview, offer, rejected or withdrawn
    current_stage: str | None


def derive(events: list[InterviewEvent]) -> Milestones:
    """Milestones and status from an application's events (pure).

    * A cancelled event did not happen. Anything else from the employer (even a
      scheduled screen or a no-show) means they responded.
    * An interview was received when a round was scheduled or held.
    * The latest offer/rejection/withdrawal decides the final status; an
      application with interview rounds and no ending is 'interview'.
    """
    live = [e for e in events if e.status != "cancelled"]

    def first(stages: tuple[str, ...]) -> datetime | None:
        times = [e.occurred_at for e in live if e.stage in stages]
        return min(times) if times else None

    employer = [e for e in live if e.stage != "withdrawal"]
    responded = min((e.occurred_at for e in employer), default=None)
    endings = sorted((e for e in live if e.stage in _TERMINAL_STATUS),
                     key=lambda e: e.occurred_at)  # fmt: skip
    first_round = first(INTERVIEW_ROUNDS)
    if endings:
        status = _TERMINAL_STATUS[endings[-1].stage]
    elif first_round is not None:
        status = "interview"
    else:
        status = "submitted"
    order = {s: i for i, s in enumerate(INTERVIEW_STAGES)}
    latest = max(live, key=lambda e: (e.occurred_at, order[e.stage]), default=None)
    return Milestones(
        responded_at=responded,
        first_interview_at=first_round,
        offer_at=first(("offer",)),
        rejected_at=first(("rejection",)),
        withdrawn_at=first(("withdrawal",)),
        status=status,
        current_stage=latest.stage if latest else None,
    )


class OutcomeService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = OutcomeRepository(session)

    # ------------------------------------------------------------- reads
    async def pipeline(self, statuses: list[str] | None = None) -> list[PipelineItem]:
        rows = await self.repo.pipeline(statuses=statuses)
        events = await self.repo.events_for([r.application.id for r in rows])
        by_app: dict[uuid.UUID, list[InterviewEvent]] = {}
        for e in events:
            by_app.setdefault(e.application_id, []).append(e)
        return [self._item(r, by_app.get(r.application.id, [])) for r in rows]

    async def detail(self, application_id: uuid.UUID) -> ApplicationOutcomes:
        rows = await self.repo.pipeline(
            statuses=("drafted", "ready", "submitted", "interview", "rejected", "offer",
                      "withdrawn"),
            application_ids=[application_id],
        )  # fmt: skip
        if not rows:
            raise NotFoundError("Application not found", {"application_id": str(application_id)})
        events = await self.repo.events_for([application_id])
        item = self._item(rows[0], events)
        timeline = await self.timeline(application_ids=[application_id])
        return ApplicationOutcomes(
            **item.model_dump(),
            interview_events=[InterviewEventRead.model_validate(e) for e in events],
            timeline=timeline,
        )

    async def timeline(
        self, *, application_ids: list[uuid.UUID] | None = None, limit: int = 200
    ) -> list[TimelineEntry]:
        """Everything that happened, newest first: packages generated and
        approved, applications submitted, and every interview event."""
        statuses = ("drafted", "ready", "submitted", "interview", "rejected", "offer", "withdrawn")
        rows = await self.repo.pipeline(statuses=statuses, application_ids=application_ids)
        entries: list[TimelineEntry] = []
        names = {r.application.id: (r.job.title, r.company.name) for r in rows}
        for m in await self.repo.package_milestones(application_ids, limit=limit):
            if m.generated_at:
                entries.append(TimelineEntry(
                    at=m.generated_at, kind="package_generated",
                    label=f"Package generated (version {m.version})",
                    application_id=m.application_id, job_id=m.job_id, job_title=m.job_title,
                    company_name=m.company_name, detail={"package_id": str(m.package_id)},
                ))  # fmt: skip
            if m.approved_at:
                entries.append(TimelineEntry(
                    at=m.approved_at, kind="package_approved",
                    label=f"Package approved (version {m.version})",
                    application_id=m.application_id, job_id=m.job_id, job_title=m.job_title,
                    company_name=m.company_name, detail={"package_id": str(m.package_id)},
                ))  # fmt: skip
        for r in rows:
            if r.application.submitted_at:
                entries.append(TimelineEntry(
                    at=r.application.submitted_at, kind="submitted", label="Application submitted",
                    application_id=r.application.id, job_id=r.job.id, job_title=r.job.title,
                    company_name=r.company.name,
                ))  # fmt: skip
        for e in await self.repo.events_for(list(names)):
            title, company = names[e.application_id]
            entries.append(TimelineEntry(
                at=e.occurred_at, kind=e.stage, label=STAGE_LABEL[e.stage],
                application_id=e.application_id, job_id=next(
                    r.job.id for r in rows if r.application.id == e.application_id),
                job_title=title, company_name=company, status=e.status,
                detail={"event_id": str(e.id), "notes": e.notes} if e.notes else
                {"event_id": str(e.id)},
            ))  # fmt: skip
        entries.sort(key=lambda t: t.at, reverse=True)
        return entries[:limit]

    # ------------------------------------------------------------ writes
    async def add_event(
        self, application_id: uuid.UUID, body: InterviewEventCreate
    ) -> ApplicationOutcomes:
        app = await self._sent_application(application_id)
        _validate(body.stage, body.status, body.occurred_at)
        event = InterviewEvent(
            application_id=app.id, stage=body.stage, status=body.status,
            occurred_at=body.occurred_at, notes=(body.notes or "").strip() or None,
        )  # fmt: skip
        self.session.add(event)
        await self.session.flush()
        await self._log(app, "outcome_recorded", event)
        await self._recompute(app)
        return await self.detail(app.id)

    async def update_event(
        self, application_id: uuid.UUID, event_id: uuid.UUID, body: InterviewEventUpdate
    ) -> ApplicationOutcomes:
        app = await self._sent_application(application_id)
        event = await self.repo.event(app.id, event_id)
        if event is None:
            raise NotFoundError("Interview event not found", {"event_id": str(event_id)})
        changes = body.model_dump(exclude_unset=True)
        stage = changes.get("stage", event.stage)
        status = changes.get("status", event.status)
        occurred = changes.get("occurred_at", event.occurred_at)
        _validate(stage, status, occurred)
        event.stage, event.status, event.occurred_at = stage, status, occurred
        if "notes" in changes:
            event.notes = (changes["notes"] or "").strip() or None
        await self.session.flush()
        await self._log(app, "outcome_updated", event)
        await self._recompute(app)
        return await self.detail(app.id)

    async def delete_event(self, application_id: uuid.UUID, event_id: uuid.UUID) -> None:
        app = await self._sent_application(application_id)
        event = await self.repo.event(app.id, event_id)
        if event is None:
            raise NotFoundError("Interview event not found", {"event_id": str(event_id)})
        await self._log(app, "outcome_removed", event)
        await self.session.delete(event)
        await self.session.flush()
        await self._recompute(app)

    # ----------------------------------------------------------- helpers
    async def _sent_application(self, application_id: uuid.UUID) -> Application:
        app = await self.session.get(Application, application_id, with_for_update=True)
        if app is None:
            raise NotFoundError("Application not found", {"application_id": str(application_id)})
        if app.submitted_at is None:
            raise ConflictError(
                "This application has not been submitted yet. Submit it (or mark the package "
                "as applied) before recording outcomes."
            )
        return app

    async def _recompute(self, app: Application) -> None:
        m = derive(await self.repo.events_for([app.id]))
        app.responded_at, app.first_interview_at = m.responded_at, m.first_interview_at
        app.offer_at, app.rejected_at, app.withdrawn_at = m.offer_at, m.rejected_at, m.withdrawn_at
        if app.status != m.status:
            previous = app.status
            app.status, app.status_updated_at = m.status, _now()
            await PackageRepository(self.session).add_event(
                app.id, event_type="status_changed", from_status=previous, to_status=m.status,
                actor="user", detail={"reason": "outcome"},
            )  # fmt: skip
        await self.session.flush()

    async def _log(self, app: Application, kind: str, event: InterviewEvent) -> None:
        detail: dict[str, Any] = {
            "event_id": str(event.id), "stage": event.stage, "status": event.status,
            "occurred_at": event.occurred_at.isoformat(),
        }  # fmt: skip
        await PackageRepository(self.session).add_event(
            app.id, event_type=kind, actor="user", detail=detail
        )

    def _item(self, row: PipelineRow, events: list[InterviewEvent]) -> PipelineItem:
        a = row.application
        m = derive(events)
        now = _now()
        soon = now - FUTURE_TOLERANCE
        upcoming = sorted(
            (e for e in events if e.status == "scheduled" and e.occurred_at >= soon),
            key=lambda e: e.occurred_at,
        )
        return PipelineItem(
            application_id=a.id,
            job_id=row.job.id,
            job_title=row.job.title,
            company_id=row.company.id,
            company_name=row.company.name,
            industry=row.company.industry,
            platform=row.company.source,
            package_id=row.package_id,
            status=a.status,
            current_stage=m.current_stage,
            next_scheduled=InterviewEventRead.model_validate(upcoming[0]) if upcoming else None,
            submitted_at=a.submitted_at,
            responded_at=a.responded_at,
            first_interview_at=a.first_interview_at,
            offer_at=a.offer_at,
            rejected_at=a.rejected_at,
            withdrawn_at=a.withdrawn_at,
            days_since_submitted=max(0, (now - a.submitted_at).days) if a.submitted_at else None,
            events=len(events),
        )


def _validate(stage: str, status: str, occurred_at: datetime) -> None:
    if stage in ALWAYS_COMPLETED and status != "completed":
        raise DomainValidationError(
            f"A {STAGE_LABEL[stage].lower()} has either happened or not: record it as completed."
        )
    if occurred_at.tzinfo is None:
        raise DomainValidationError("Give the date with a time zone (ISO 8601).")
    if status in ("completed", "no_show") and occurred_at > _now() + FUTURE_TOLERANCE:
        raise DomainValidationError(
            "A completed event cannot be in the future: record it as scheduled."
        )
