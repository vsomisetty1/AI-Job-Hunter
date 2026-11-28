"""Application package workflow (request transaction): reads and state changes.

    generated -> reviewed -> approved -> submitted
         \\-----------\\---------\\--> rejected
    any non-final package -> regenerate (new version; the old one is superseded)

Approval creates or updates the job's `applications` row (status 'ready',
APPROVAL_MODE) with the package's resume, cover letter and score; browser
automation (`automation_service`) works from that row. This module never
submits anything: 'submitted' is recorded only when the user says they applied.
Generation itself is in `package_generator`.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.agent_7_resume_generation import (
    DOCX_TYPE,
    PDF_TYPE,
)
from app.core.exceptions import ConflictError, NotFoundError
from app.models.application import Application
from app.models.application_package import ApplicationPackage, a_status
from app.models.candidate_profile import CandidateProfile
from app.models.cover_letter import CoverLetter
from app.models.job import Job
from app.models.resume_version import ResumeVersion
from app.repositories.candidate_profile_repository import CandidateProfileRepository
from app.repositories.job_repository import JobRepository
from app.repositories.package_repository import PackageRepository, PackageRow
from app.schemas.common import Page
from app.schemas.job import JobSummary
from app.schemas.package import (
    AnswerRead,
    CoverLetterRead,
    PackageDetail,
    PackageSummary,
    TailoredResumeRead,
)
from app.schemas.parsed_resume import ParsedResume
from app.services.package_inputs import (
    PackageInputError,
    utcnow,
)
from app.storage import StorageBackend

REGENERATABLE = ("generated", "reviewed", "approved", "rejected", "failed")
EDITABLE = ("generated", "reviewed")
DOCS = ("resume", "cover-letter", "original-resume")


class PackageWorkflow:
    """Reads and state changes, inside the request's unit of work."""

    def __init__(self, session: AsyncSession, storage: StorageBackend) -> None:
        self.session = session
        self.storage = storage
        self.repo = PackageRepository(session)

    # ------------------------------------------------------------ create
    async def create(
        self, job_id: uuid.UUID, *, use_llm: bool, include_cover_letter: bool
    ) -> ApplicationPackage:
        """New package row in 'generating'; the caller starts the background job."""
        profile = await CandidateProfileRepository(self.session).get_active()
        if profile is None:
            raise PackageInputError("Upload a resume first: packages are built from your profile.")
        job = await self.session.get(Job, job_id)
        if job is None:
            raise NotFoundError("Job not found", {"job_id": str(job_id)})
        if job.status == "expired":
            raise PackageInputError("This job has expired.")
        live = await self.repo.live(job_id, profile.id)
        if live is not None:
            raise ConflictError(
                "This job already has a package; open it or regenerate it.",
                {"package_id": str(live.id), "status": live.status},
            )
        return await self._new(job_id, profile.id, use_llm, include_cover_letter)

    async def _new(
        self, job_id: uuid.UUID, profile_id: uuid.UUID, use_llm: bool, include_cover_letter: bool
    ) -> ApplicationPackage:
        pkg = ApplicationPackage(
            job_id=job_id,
            profile_id=profile_id,
            version_number=await self.repo.next_version(job_id, profile_id),
            status="generating",
            generation={"use_llm": use_llm, "include_cover_letter": include_cover_letter},
        )
        return await self.repo.add(pkg)

    async def regenerate(
        self, package_id: uuid.UUID, *, use_llm: bool, include_cover_letter: bool
    ) -> ApplicationPackage:
        old = await self._lock(package_id)
        if old.status not in REGENERATABLE:
            raise ConflictError(f"{a_status(old.status)} package cannot be regenerated.")
        newer = await self.repo.next_version(old.job_id, old.profile_id)
        if newer != old.version_number + 1:
            raise ConflictError("Only the newest package of a job can be regenerated.")
        if old.status in ("generated", "reviewed", "approved"):
            await self._withdraw_approval(old, "Package regenerated")
            old.status = "superseded"
            await self.session.flush()
        return await self._new(old.job_id, old.profile_id, use_llm, include_cover_letter)

    # --------------------------------------------------------- transitions
    async def review(self, package_id: uuid.UUID) -> ApplicationPackage:
        pkg = await self._lock(package_id)
        if pkg.status == "generated":
            pkg.status, pkg.reviewed_at = "reviewed", utcnow()
        elif pkg.status not in ("reviewed", "approved", "submitted"):
            raise ConflictError(f"{a_status(pkg.status)} package cannot be marked reviewed.")
        return pkg

    async def approve(self, package_id: uuid.UUID, notes: str | None) -> ApplicationPackage:
        pkg = await self._lock(package_id)
        if pkg.status not in ("generated", "reviewed"):
            raise ConflictError(f"{a_status(pkg.status)} package cannot be approved.")
        if pkg.resume_version_id is None:
            raise ConflictError("The package has no tailored resume (was it deleted?).")
        job = await self.session.get(Job, pkg.job_id)
        if job is None or job.status == "expired":
            raise ConflictError("This job is no longer posted, so its package cannot be approved.")
        now = utcnow()
        app = await self.repo.application_for(pkg.job_id, pkg.profile_id)
        if app is not None and app.status not in ("drafted", "ready"):
            raise ConflictError(f"You already applied to this job (application is {app.status}).")
        created = app is None
        if app is None:
            app = Application(job_id=pkg.job_id, profile_id=pkg.profile_id)
            self.session.add(app)
            await self.session.flush()
            await self.repo.add_event(
                app.id,
                event_type="created",
                to_status="drafted",
                actor="user",
                detail={"package_id": str(pkg.id)},
            )
        previous = app.status
        app.resume_version_id = pkg.resume_version_id
        app.cover_letter_id = pkg.cover_letter_id
        app.job_score_id = pkg.job_score_id
        app.application_mode = "APPROVAL_MODE"
        app.status, app.approved_at, app.status_updated_at = "ready", now, now
        await self.repo.add_event(
            app.id,
            event_type="approved",
            from_status=None if created else previous,
            to_status="ready",
            actor="user",
            detail={"package_id": str(pkg.id), "version": pkg.version_number},
        )
        pkg.status, pkg.approved_at, pkg.application_id = "approved", now, app.id
        pkg.reviewed_at = pkg.reviewed_at or now
        pkg.review_notes = notes
        job = await self.session.get(Job, pkg.job_id)
        if job is not None and job.status in ("new", "scored"):
            job.status = "shortlisted"
        await self.session.flush()
        return pkg

    async def reject(self, package_id: uuid.UUID, reason: str) -> ApplicationPackage:
        pkg = await self._lock(package_id)
        if pkg.status not in ("generated", "reviewed", "approved"):
            raise ConflictError(f"{a_status(pkg.status)} package cannot be rejected.")
        await self._withdraw_approval(pkg, f"Package rejected: {reason}")
        pkg.status, pkg.rejected_at, pkg.rejection_reason = "rejected", utcnow(), reason
        await self.session.flush()
        return pkg

    async def mark_submitted(self, package_id: uuid.UUID) -> ApplicationPackage:
        """Record that the user applied with this package (nothing is sent)."""
        pkg = await self._lock(package_id)
        if pkg.status != "approved":
            raise ConflictError("Only an approved package can be marked as submitted.")
        now = utcnow()
        if pkg.application_id is not None:
            app = await self.session.get(Application, pkg.application_id)
            if app is not None:
                previous = app.status
                app.status, app.submitted_at, app.status_updated_at = "submitted", now, now
                app.automation_state = "completed"  # applied by hand: nothing left to automate
                await self.repo.add_event(
                    app.id,
                    event_type="submitted",
                    from_status=previous,
                    to_status="submitted",
                    actor="user",
                    detail={"package_id": str(pkg.id), "manual": True},
                )
        pkg.status, pkg.submitted_at = "submitted", now
        job = await self.session.get(Job, pkg.job_id)
        if job is not None and job.status != "expired":
            job.status = "applied"
        await self.session.flush()
        return pkg

    async def update_answer(
        self, package_id: uuid.UUID, answer_id: uuid.UUID, text: str
    ) -> AnswerRead:
        pkg = await self._lock(package_id)
        if pkg.status not in EDITABLE:
            raise ConflictError(
                f"Answers of a {pkg.status} package cannot be edited; regenerate or reject it."
            )
        answer = await self.repo.answer(package_id, answer_id)
        if answer is None:
            raise NotFoundError("Answer not found", {"answer_id": str(answer_id)})
        answer.answer, answer.source, answer.needs_review = text, "user", False
        answer.confidence = None
        answer.evidence = [*answer.evidence, {"source": "user", "fact": "edited by you"}]
        await self.session.flush()
        await self.session.refresh(answer)
        return AnswerRead.model_validate(answer)

    async def _withdraw_approval(self, pkg: ApplicationPackage, why: str) -> None:
        """An approved package that is rejected or replaced no longer authorises
        the application: it goes back to 'drafted'."""
        if pkg.application_id is None:
            return
        app = await self.session.get(Application, pkg.application_id)
        if app is not None and app.status == "ready":
            app.status, app.approved_at, app.status_updated_at = "drafted", None, utcnow()
            await self.repo.add_event(
                app.id,
                event_type="status_changed",
                from_status="ready",
                to_status="drafted",
                actor="user",
                detail={"package_id": str(pkg.id), "reason": why},
            )

    async def _lock(self, package_id: uuid.UUID) -> ApplicationPackage:
        pkg = await self.repo.lock(package_id)
        if pkg is None:
            raise NotFoundError("Package not found", {"package_id": str(package_id)})
        return pkg

    # ------------------------------------------------------------- reads
    async def search(
        self, statuses: list[str] | None, job_id: uuid.UUID | None, limit: int, offset: int
    ) -> Page[PackageSummary]:
        rows, total = await self.repo.search(
            statuses=statuses, job_id=job_id, limit=limit, offset=offset
        )
        return Page[PackageSummary](
            items=[_summary(r) for r in rows], total=total, limit=limit, offset=offset
        )

    async def detail(self, package_id: uuid.UUID) -> PackageDetail:
        row = await self.repo.get_row(package_id)
        if row is None:
            raise NotFoundError("Package not found", {"package_id": str(package_id)})
        pkg = row[0]
        job_row = await JobRepository(self.session).get_with_company(pkg.job_id)
        if job_row is None:
            raise NotFoundError("Job not found", {"job_id": str(pkg.job_id)})
        job, company_name, source = job_row
        job_summary = JobSummary(
            **{
                f: getattr(job, f)
                for f in JobSummary.model_fields
                if f not in {"company_name", "source", "score", "score_method"}
            },
            company_name=company_name,
            source=source,
            score=pkg.score_snapshot.get("overall"),
            score_method=pkg.score_snapshot.get("method"),
        )
        tailored = await self._version(pkg.resume_version_id)
        base = await self._version(pkg.base_resume_version_id)
        cover = (
            await self.session.get(CoverLetter, pkg.cover_letter_id)
            if pkg.cover_letter_id
            else None
        )
        answers = await self.repo.answers(pkg.id)
        summary = _summary(row)
        return PackageDetail(
            **summary.model_dump(),
            job=job_summary,
            score_snapshot=pkg.score_snapshot,
            generation=pkg.generation,
            review_notes=pkg.review_notes,
            rejection_reason=pkg.rejection_reason,
            application_id=pkg.application_id,
            base_resume=ParsedResume.model_validate(base.content) if base else None,
            base_resume_version_id=pkg.base_resume_version_id,
            tailored_resume=TailoredResumeRead.model_validate(tailored).model_copy(
                update={"has_pdf": bool(tailored.pdf_path), "has_docx": bool(tailored.docx_path)}
            )
            if tailored
            else None,
            cover_letter=CoverLetterRead.model_validate(cover).model_copy(
                update={"has_pdf": bool(cover.pdf_path), "has_docx": bool(cover.docx_path)}
            )
            if cover
            else None,
            answers=[AnswerRead.model_validate(a) for a in answers],
        )

    async def _version(self, version_id: uuid.UUID | None) -> ResumeVersion | None:
        return await self.session.get(ResumeVersion, version_id) if version_id else None

    async def file(self, package_id: uuid.UUID, doc: str, fmt: str) -> tuple[bytes, str, str]:
        """(data, filename, content type) of one generated document."""
        if doc not in DOCS or fmt not in ("pdf", "docx"):
            raise NotFoundError("Unknown document", {"doc": doc, "format": fmt})
        row = await self.repo.get_row(package_id)
        if row is None:
            raise NotFoundError("Package not found", {"package_id": str(package_id)})
        pkg, _title, company, _ = row
        holder: ResumeVersion | CoverLetter | None
        if doc == "cover-letter":
            holder = (
                await self.session.get(CoverLetter, pkg.cover_letter_id)
                if pkg.cover_letter_id
                else None
            )
        else:
            holder = await self._version(
                pkg.resume_version_id if doc == "resume" else pkg.base_resume_version_id
            )
        path = (holder.pdf_path if fmt == "pdf" else holder.docx_path) if holder else None
        if not path:
            raise NotFoundError("This document has not been generated.", {"doc": doc})
        profile = await self.session.get(CandidateProfile, pkg.profile_id)
        name = (profile.full_name if profile else "Candidate").replace(" ", "_")
        label = {
            "resume": "Resume",
            "cover-letter": "Cover_Letter",
            "original-resume": "Resume_Original",
        }[doc]
        safe_company = (
            "".join(c for c in company if c.isalnum() or c in " -").strip().replace(" ", "_")
        )
        filename = f"{name}_{label}_{safe_company or 'Company'}.{fmt}"
        return await self.storage.get(path), filename, PDF_TYPE if fmt == "pdf" else DOCX_TYPE


def _summary(row: PackageRow) -> PackageSummary:
    pkg, title, company, needs_review = row
    return PackageSummary(
        id=pkg.id,
        job_id=pkg.job_id,
        job_title=title,
        company_name=company,
        version_number=pkg.version_number,
        status=pkg.status,
        score=pkg.score_snapshot.get("overall"),
        score_method=pkg.score_snapshot.get("method"),
        answers_needing_review=int(needs_review or 0),
        error=pkg.error,
        generated_at=pkg.generated_at,
        reviewed_at=pkg.reviewed_at,
        approved_at=pkg.approved_at,
        rejected_at=pkg.rejected_at,
        submitted_at=pkg.submitted_at,
        created_at=pkg.created_at,
        updated_at=pkg.updated_at,
    )
