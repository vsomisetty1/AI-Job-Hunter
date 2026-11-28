"""Application automation, approval mode: the execution pipeline and the
submission tracker.

    approved package -> start (queued) -> run: open, upload, fill, validate,
    screenshot -> waiting_for_review -> [user: edit / retry / cancel]
    -> user confirms -> submitting -> submitted | back to review | failed

Rules this module enforces (and the database backs up):
* only an approved package whose application is "ready" and whose job is still
  posted can start; one active run per application;
* nothing is submitted unless the user called `submit` with confirm=true while
  the filled form is open; `confirmed_at` is recorded before the click;
* a submission is never retried automatically: if the site does not confirm,
  the run fails as "unconfirmed" and the user checks before trying again;
* transient failures while preparing (crash, timeout, network) are retried
  automatically up to AUTOMATION_MAX_ATTEMPTS, resuming from the checkpoint.
"""

import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.agent_10_application_agent import (
    ApplicationAgent,
    ApplyRun,
    ReviewReport,
)
from app.automation.browser_manager import BrowserManager, SessionRegistry
from app.automation.checkpoints import Checkpoint
from app.automation.field_matcher import ApplicantFacts
from app.automation.platforms import adapter_for
from app.automation.recovery import classify, hint
from app.core.config import Settings
from app.core.exceptions import ConflictError, DomainValidationError, NotFoundError
from app.models.application import Application
from app.models.application_package import ApplicationPackage
from app.models.application_submission import (
    ACTIVE_STATUSES,
    ApplicationSubmission,
)
from app.models.company import Company
from app.models.job import Job
from app.repositories.automation_repository import (
    BrowserSessionRepository,
    SubmissionRepository,
)
from app.repositories.package_repository import PackageRepository
from app.schemas.automation import (
    AutomationLogRead,
    AutomationQueue,
    AutomationStatus,
    ReadyPackage,
    SubmissionDetail,
    SubmissionSummary,
)
from app.schemas.common import Page
from app.services.automation_facts import applicant_facts
from app.services.automation_recorder import DbRecorder
from app.services.automation_views import (
    latest_per_application,
    submission_detail,
    submission_summary,
)
from app.storage import StorageBackend

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(UTC)


class AutomationService:
    def __init__(
        self,
        settings: Settings,
        sessionmaker: async_sessionmaker[AsyncSession],
        storage: StorageBackend,
        browser: BrowserManager,
        registry: SessionRegistry,
        agent: ApplicationAgent,
    ) -> None:
        self.settings = settings
        self.sessionmaker = sessionmaker
        self.storage = storage
        self.browser = browser
        self.registry = registry
        self.agent = agent

    # ================================================================ reads
    def status(self) -> AutomationStatus:
        return AutomationStatus(
            enabled=self.settings.automation_enabled,
            mode="APPROVAL_MODE",
            autonomous_available=False,
            headless=self.settings.automation_headless,
            browser_running=self.browser.alive,
            open_sessions=self.registry.open_count,
            max_sessions=self.settings.automation_max_sessions,
            session_idle_minutes=self.settings.automation_session_idle_minutes,
        )

    async def queue(self) -> AutomationQueue:
        async with self.sessionmaker() as session:
            repo = SubmissionRepository(session)
            ready = await repo.ready_packages()
            active, _ = await repo.search(statuses=ACTIVE_STATUSES, limit=200, offset=0)
            failed, _ = await repo.search(statuses=("failed",), limit=50, offset=0)
        active_apps = {r.submission.application_id for r in active}
        attention = [r for r in failed if r.submission.application_id not in active_apps]
        # A failed run's application shows once, under "needs attention".
        failed_apps = {r.submission.application_id for r in attention}
        return AutomationQueue(
            ready=[
                ReadyPackage(
                    package_id=r.package.id,
                    application_id=r.application_id,
                    job_id=r.package.job_id,
                    job_title=r.job_title,
                    company_name=r.company_name,
                    platform=r.platform,
                    supported=adapter_for(r.platform) is not None,
                    job_status=r.job_status,
                    approved_at=r.package.approved_at,
                )
                for r in ready
                if r.application_id not in failed_apps
            ],
            active=[
                submission_summary(r, live=self.registry.is_live(r.submission.id)) for r in active
            ],
            needs_attention=[
                submission_summary(r, live=self.registry.is_live(r.submission.id))
                for r in latest_per_application(attention)
            ],
        )

    async def history(
        self, statuses: list[str] | None, limit: int, offset: int
    ) -> Page[SubmissionSummary]:
        async with self.sessionmaker() as session:
            rows, total = await SubmissionRepository(session).search(
                statuses=statuses, limit=limit, offset=offset
            )
        return Page(
            items=[
                submission_summary(r, live=self.registry.is_live(r.submission.id)) for r in rows
            ],
            total=total,
            limit=limit,
            offset=offset,
        )

    async def detail(self, submission_id: uuid.UUID) -> SubmissionDetail:
        async with self.sessionmaker() as session:
            row = await SubmissionRepository(session).get_row(submission_id)
        if row is None:
            raise NotFoundError("Submission not found", {"submission_id": str(submission_id)})
        return submission_detail(row, live=self.registry.is_live(row.submission.id))

    async def logs(
        self,
        *,
        submission_id: uuid.UUID | None,
        levels: list[str] | None,
        limit: int,
        offset: int,
    ) -> Page[AutomationLogRead]:
        async with self.sessionmaker() as session:
            rows, total = await SubmissionRepository(session).logs(
                submission_id=submission_id, levels=levels, limit=limit, offset=offset
            )
        return Page(
            items=[
                AutomationLogRead(
                    id=log.id,
                    submission_id=log.submission_id,
                    job_title=title,
                    company_name=company,
                    level=log.level,
                    step=log.step,
                    message=log.message,
                    detail=log.detail,
                    created_at=log.created_at,
                )  # fmt: skip
                for log, title, company in rows
            ],
            total=total,
            limit=limit,
            offset=offset,
        )

    async def screenshot(self, submission_id: uuid.UUID, index: int) -> bytes:
        async with self.sessionmaker() as session:
            sub = await session.get(ApplicationSubmission, submission_id)
        if sub is None or not 1 <= index <= len(sub.screenshots):
            raise NotFoundError("Screenshot not found", {"index": index})
        return await self.storage.get(str(sub.screenshots[index - 1]["path"]))

    # =============================================================== start
    async def start(self, package_id: uuid.UUID) -> ApplicationSubmission:
        if not self.settings.automation_enabled:
            raise ConflictError("Application automation is turned off (AUTOMATION_ENABLED).")
        async with self.sessionmaker() as session, session.begin():
            pkg = await session.get(ApplicationPackage, package_id, with_for_update=True)
            if pkg is None:
                raise NotFoundError("Package not found", {"package_id": str(package_id)})
            if pkg.status != "approved" or pkg.application_id is None:
                raise ConflictError("Only an approved package can be filled into an application.")
            app = await session.get(Application, pkg.application_id, with_for_update=True)
            if app is None or app.status != "ready":
                raise ConflictError("The application is not ready (approve the package again).")
            job = await session.get(Job, pkg.job_id)
            company = await session.get(Company, job.company_id) if job else None
            if job is None or company is None or job.status == "expired":
                raise ConflictError("This job is no longer posted.")
            adapter = adapter_for(company.source)
            if adapter is None:
                raise DomainValidationError(f"{company.source} applications are not supported.")
            repo = SubmissionRepository(session)
            if await repo.active_for(app.id) is not None:
                raise ConflictError("This application already has a run in progress.")
            if pkg.resume_version_id is None:
                raise ConflictError("The package has no tailored resume (was it deleted?).")
            sub = ApplicationSubmission(
                application_id=app.id,
                package_id=pkg.id,
                platform=company.source,
                apply_url=adapter.application_url(company.slug, job.external_id, job.url),
            )
            session.add(sub)
            app.automation_state = "in_progress"
            await session.flush()
            await PackageRepository(session).add_event(
                app.id,
                event_type="automation_started",
                actor="user",
                detail={"submission_id": str(sub.id), "mode": "APPROVAL_MODE"},
            )
            await repo.add_log(sub.id, "info", "queued", "Queued (approval mode)", {})
        return sub

    async def retry(self, submission_id: uuid.UUID) -> ApplicationSubmission:
        """Reopen the form and refill it from the checkpoint (and your edits)."""
        async with self.sessionmaker() as session, session.begin():
            repo = SubmissionRepository(session)
            sub = await self._locked(repo, submission_id)
            if sub.status not in ("failed", "waiting_for_review"):
                raise ConflictError(f"A {sub.status.replace('_', ' ')} run cannot be retried.")
            app = await session.get(Application, sub.application_id)
            if app is None or app.status != "ready":
                raise ConflictError("The application is no longer ready (was it rejected?).")
            other = await repo.active_for(sub.application_id)
            if other is not None and other.id != sub.id:
                raise ConflictError("Another run for this application is in progress.")
            await self._check_still_approved(session, sub)
            sub.status, sub.error, sub.error_kind = "queued", None, None
            sub.failed_at, sub.confirmed_at, sub.queued_at = None, None, _now()
            app.automation_state = "in_progress"
            await repo.add_log(sub.id, "info", "queued", "Retry requested", {})
            await PackageRepository(session).add_event(
                app.id, event_type="retry", actor="user", detail={"submission_id": str(sub.id)}
            )
        await self.registry.release(submission_id)
        return sub

    async def cancel(self, submission_id: uuid.UUID) -> SubmissionDetail:
        async with self.sessionmaker() as session, session.begin():
            repo = SubmissionRepository(session)
            sub = await self._locked(repo, submission_id)
            if sub.status == "submitting":
                raise ConflictError("The application is being submitted and cannot be cancelled.")
            if sub.status not in ACTIVE_STATUSES and sub.status != "failed":
                raise ConflictError(f"A {sub.status} run cannot be cancelled.")
            sub.status, sub.cancelled_at, sub.confirmed_at = "cancelled", _now(), None
            app = await session.get(Application, sub.application_id)
            if app is not None and app.automation_state != "completed":
                app.automation_state = "pending"
                await PackageRepository(session).add_event(
                    app.id, event_type="note", actor="user",
                    detail={"submission_id": str(sub.id), "automation": "cancelled"},
                )  # fmt: skip
            await repo.add_log(sub.id, "info", sub.step, "Cancelled by you; nothing was submitted",
                               {})  # fmt: skip
        await self.registry.release(submission_id)
        return await self.detail(submission_id)

    # ================================================================= run
    async def run(self, submission_id: uuid.UUID) -> str:
        """Background task: prepare the form and stop for review."""
        rec = DbRecorder(self.sessionmaker, self.storage, submission_id)
        await self.registry.acquire(submission_id)  # waits while the browser slots are full
        keep_slot = False
        try:
            for attempt in range(1, self.settings.automation_max_attempts + 1):
                run = await self._begin(submission_id)
                if run is None:
                    return "skipped"
                try:
                    report = await self.agent.prepare(run, rec)
                except Exception as exc:
                    logger.warning("automation run failed", exc_info=True)
                    failure = classify(exc)
                    await rec.log("error" if not failure.retryable else "warning", "run",
                                  failure.message, kind=failure.kind, attempt=attempt)  # fmt: skip
                    if failure.retryable and attempt < self.settings.automation_max_attempts:
                        await rec.log("info", "run", "Retrying from the last checkpoint")
                        continue
                    await self._fail(submission_id, failure.kind, failure.message)
                    return "failed"
                keep_slot = await self._ready_for_review(submission_id, report)
                return "waiting_for_review" if keep_slot else "cancelled"
            return "failed"  # pragma: no cover - the loop always returns
        finally:
            if not keep_slot:
                await self.registry.release(submission_id)

    async def _begin(self, submission_id: uuid.UUID) -> ApplyRun | None:
        async with self.sessionmaker() as session, session.begin():
            sub = await session.get(ApplicationSubmission, submission_id, with_for_update=True)
            if sub is None or sub.status not in ("queued", "in_progress"):
                return None  # cancelled while waiting
            pkg = await session.get(ApplicationPackage, sub.package_id) if sub.package_id else None
            app = await session.get(Application, sub.application_id)
            if pkg is None or app is None:
                await self._fail_in(session, sub, "internal", "The package was deleted.")
                return None
            sub.status, sub.attempts = "in_progress", sub.attempts + 1
            sub.started_at = sub.started_at or _now()
            facts, files = await applicant_facts(session, self.storage, pkg)
            state = await BrowserSessionRepository(session).state(sub.platform)
            return ApplyRun(
                submission_id=sub.id,
                application_id=sub.application_id,
                job_id=app.job_id,
                platform=sub.platform,
                url=sub.apply_url,
                facts=facts,
                files=files,
                edits=dict(sub.edits),
                checkpoint=Checkpoint.from_json(sub.checkpoint),
                browser_state=state,
                attempt=sub.attempts,
            )

    async def _ready_for_review(self, submission_id: uuid.UUID, report: ReviewReport) -> bool:
        async with self.sessionmaker() as session, session.begin():
            sub = await session.get(ApplicationSubmission, submission_id, with_for_update=True)
            if sub is None or sub.status != "in_progress":
                return False  # cancelled meanwhile: the slot is released
            sub.status, sub.step, sub.review = "waiting_for_review", "review", report.as_json()
            sub.review_ready_at = _now()
            app = await session.get(Application, sub.application_id)
            if app is not None:
                app.automation_state = "needs_manual"
                await PackageRepository(session).add_event(
                    app.id, event_type="needs_manual", actor="agent",
                    detail={"submission_id": str(sub.id), "missing": len(report.missing),
                            "problems": len(report.problems)},
                )  # fmt: skip
        return True

    async def _fail(self, submission_id: uuid.UUID, kind: str, message: str) -> None:
        async with self.sessionmaker() as session, session.begin():
            sub = await session.get(ApplicationSubmission, submission_id, with_for_update=True)
            if sub is not None and sub.status not in ("cancelled", "submitted"):
                await self._fail_in(session, sub, kind, message)

    async def _fail_in(
        self, session: AsyncSession, sub: ApplicationSubmission, kind: str, message: str
    ) -> None:
        sub.status, sub.error_kind, sub.error = "failed", kind, message[:2000]
        sub.failed_at, sub.confirmed_at = _now(), None
        app = await session.get(Application, sub.application_id)
        if app is not None:
            app.automation_state, app.last_error = "failed", message[:2000]
            await PackageRepository(session).add_event(
                app.id, event_type="failed", actor="agent",
                detail={"submission_id": str(sub.id), "kind": kind, "message": message[:500]},
            )  # fmt: skip

    # ============================================================ review
    async def edit(
        self, submission_id: uuid.UUID, key: str, value: str | bool | list[str]
    ) -> SubmissionDetail:
        async with self.sessionmaker() as session, session.begin():
            sub = await self._locked(SubmissionRepository(session), submission_id)
            if sub.status != "waiting_for_review":
                raise ConflictError("Fields can only be changed while the run waits for review.")
            sub.edits = {**sub.edits, key: value}
            pkg = await session.get(ApplicationPackage, sub.package_id) if sub.package_id else None
            facts, files = (
                await applicant_facts(session, self.storage, pkg) if pkg else (ApplicantFacts(), {})
            )
            app = await session.get(Application, sub.application_id)
            run = ApplyRun(sub.id, sub.application_id, app.job_id if app else uuid.uuid4(),
                           sub.platform, sub.apply_url, facts, files, dict(sub.edits))  # fmt: skip
        live = self.registry.get(submission_id)
        rec = DbRecorder(self.sessionmaker, self.storage, submission_id)
        if live is None:
            await rec.log("info", "review", f"Saved your answer for {key}; it is filled on retry")
            return await self.detail(submission_id)
        async with live.lock:
            try:
                report = await self.agent.apply_edit(live, run, key, value, rec)
            except Exception as exc:
                failure = classify(exc)
                await rec.log("warning", "review", f"Could not apply your edit: {failure.message}")
                raise ConflictError(f"Could not change that field: {failure.message}") from exc
        await self._save_review(submission_id, report)
        return await self.detail(submission_id)

    async def _save_review(self, submission_id: uuid.UUID, report: ReviewReport) -> None:
        async with self.sessionmaker() as session, session.begin():
            sub = await session.get(ApplicationSubmission, submission_id)
            if sub is not None:
                sub.review = report.as_json()

    # ============================================================= submit
    async def confirm_submit(self, submission_id: uuid.UUID) -> SubmissionDetail:
        """The user's confirmation. Checks the open form once more, records the
        confirmation and moves to 'submitting'; `finish_submit` does the click."""
        live = self.registry.get(submission_id)
        async with self.sessionmaker() as session:
            sub = await session.get(ApplicationSubmission, submission_id)
            if sub is None:
                raise NotFoundError("Submission not found", {"submission_id": str(submission_id)})
            if sub.status != "waiting_for_review":
                raise ConflictError(f"Only a run waiting for review can be submitted "
                                    f"(this one is {sub.status.replace('_', ' ')}).")  # fmt: skip
        if live is None:
            raise ConflictError(
                "The browser session for this form was closed. Retry to reopen and refill it, "
                "review it, then submit."
            )
        async with live.lock:
            report = await self.agent.revalidate(live)
        await self._save_review(submission_id, report)
        if report.missing or report.problems:
            raise ConflictError(
                f"The form is not complete: {len(report.missing)} required field(s) missing and "
                f"{len(report.problems)} problem(s). Fix them in review first."
            )
        async with self.sessionmaker() as session, session.begin():
            repo = SubmissionRepository(session)
            sub = await self._locked(repo, submission_id)
            if sub.status != "waiting_for_review":
                raise ConflictError("The run changed status meanwhile; reload the page.")
            await self._check_still_approved(session, sub)
            sub.status, sub.step, sub.confirmed_at = "submitting", "submitting", _now()
            await repo.add_log(sub.id, "info", "submitting", "You confirmed the submission", {})
        return await self.detail(submission_id)

    async def finish_submit(self, submission_id: uuid.UUID) -> str:
        """Background task after `confirm_submit`. Never retried automatically."""
        rec = DbRecorder(self.sessionmaker, self.storage, submission_id)
        live = self.registry.get(submission_id)
        if live is None:
            await self._fail(
                submission_id, "interrupted",
                "The browser closed before submitting; nothing was sent. Retry.",
            )  # fmt: skip
            return "failed"
        try:
            async with live.lock:
                result = await self.agent.submit(live, rec)
        except Exception as exc:
            logger.error("submission failed", exc_info=True)
            failure = classify(exc)
            await rec.log("error", "submitting", failure.message, kind=failure.kind)
            await self._fail(
                submission_id, "unconfirmed" if failure.kind != "ats_changed" else "ats_changed",
                f"{failure.message} It is not known whether the application went through: "
                "check your email or the company's portal before retrying.",
            )  # fmt: skip
            await self.registry.release(submission_id)
            return "failed"
        if result.outcome == "submitted":
            await self._submitted(submission_id, result.confirmation or "")
            await rec.save_browser_state(
                live.platform, await self.browser.storage_state(live.context)
            )
            await self.registry.release(submission_id)
            return "submitted"
        if result.outcome in ("rejected", "captcha"):
            async with self.sessionmaker() as session, session.begin():
                sub = await session.get(ApplicationSubmission, submission_id, with_for_update=True)
                if sub is not None:
                    sub.status, sub.step, sub.confirmed_at = "waiting_for_review", "review", None
                    if result.report is not None:
                        sub.review = {**result.report.as_json(),
                                      "captcha": result.outcome == "captcha"}  # fmt: skip
            msg = (
                "The site asked for a CAPTCHA: solve it in the browser window "
                "(AUTOMATION_HEADLESS=false), then submit again."
                if result.outcome == "captcha"
                else "The form refused the submission; fix the problems shown and submit again."
            )
            await rec.log("warning", "review", msg)
            return "waiting_for_review"
        await self._fail(submission_id, "unconfirmed", hint("unconfirmed"))
        await self.registry.release(submission_id)
        return "failed"

    async def _submitted(self, submission_id: uuid.UUID, confirmation: str) -> None:
        now = _now()
        async with self.sessionmaker() as session, session.begin():
            sub = await session.get(ApplicationSubmission, submission_id, with_for_update=True)
            if sub is None:
                return
            sub.status, sub.step, sub.submitted_at = "submitted", "done", now
            sub.confirmation_text = confirmation[:2000] or None
            app = await session.get(Application, sub.application_id, with_for_update=True)
            if app is not None:
                previous = app.status
                app.status, app.submitted_at, app.status_updated_at = "submitted", now, now
                app.automation_state, app.confirmation_ref = "completed", confirmation[:500] or None
                await PackageRepository(session).add_event(
                    app.id, event_type="submitted", from_status=previous, to_status="submitted",
                    actor="agent",
                    detail={"submission_id": str(sub.id), "confirmed_by_user_at":
                            sub.confirmed_at.isoformat() if sub.confirmed_at else None},
                )  # fmt: skip
            pkg = await session.get(ApplicationPackage, sub.package_id) if sub.package_id else None
            if pkg is not None and pkg.status == "approved":
                pkg.status, pkg.submitted_at = "submitted", now
            job = await session.get(Job, app.job_id) if app else None
            if job is not None and job.status != "expired":
                job.status = "applied"
            await SubmissionRepository(session).add_log(
                submission_id, "info", "done", "Submitted: the site confirmed it",
                {"confirmation": confirmation[:500]},
            )  # fmt: skip

    # ======================================================== maintenance
    async def recover_interrupted(self) -> int:
        """At startup: runs cut off by a restart are failed (and say why)."""
        async with self.sessionmaker() as session, session.begin():
            repo = SubmissionRepository(session)
            n = await repo.interrupt(
                ("submitting",),
                "The app stopped while submitting. It is not known whether the application "
                "went through: check your email or the company's portal before retrying.",
                _now(),
            )
            n += await repo.interrupt(
                ("queued", "in_progress"),
                "The app restarted before the form was ready. Retry to start again.",
                _now(),
            )
        if n:
            logger.warning("marked %d interrupted automation run(s) failed", n)
        return n

    async def sweep_idle(self) -> int:
        """Close forms left open longer than the idle timeout (Retry reopens)."""
        closed = 0
        for sid in self.registry.idle():
            await self.registry.release(sid)
            rec = DbRecorder(self.sessionmaker, self.storage, sid)
            await rec.log("info", "review", "Closed the browser after "
                          f"{self.settings.automation_session_idle_minutes} idle minutes; "
                          "Retry reopens and refills the form")  # fmt: skip
            closed += 1
        return closed

    async def prune_logs(self) -> int:
        before = _now() - timedelta(days=self.settings.agent_run_retention_days)
        async with self.sessionmaker() as session, session.begin():
            return await SubmissionRepository(session).prune_logs(before)

    async def shutdown(self) -> None:
        await self.registry.close_all()
        await self.browser.close()

    # ============================================================ helpers
    async def _locked(self, repo: SubmissionRepository, sid: uuid.UUID) -> ApplicationSubmission:
        sub = await repo.lock(sid)
        if sub is None:
            raise NotFoundError("Submission not found", {"submission_id": str(sid)})
        return sub

    async def _check_still_approved(
        self, session: AsyncSession, sub: ApplicationSubmission
    ) -> None:
        pkg = await session.get(ApplicationPackage, sub.package_id) if sub.package_id else None
        if pkg is None or pkg.status != "approved":
            raise ConflictError("The package is no longer approved, so it cannot be submitted.")
        job = await session.get(Job, pkg.job_id)
        if job is None or job.status == "expired":
            raise ConflictError("This job is no longer posted.")
