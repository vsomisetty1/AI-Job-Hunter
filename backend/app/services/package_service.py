"""Application packages: generation (background) and the approval workflow.

Generation (`PackageGenerator`, background task, own short transactions):

    Candidate profile + primary resume (latest parsed version) + job + score
      -> Agent 6 tailored resume (every change with its reason)
      -> Agent 7 PDF/DOCX of the original and the tailored resume
      -> Agent 8 cover letter (optional) + PDF/DOCX
      -> Agent 9 answers to common application questions
      -> one `application_packages` row linking them, status 'generated'

No transaction is open while agents or Claude run. Files are written before
the rows that point to them. A failure marks the package 'failed' with the
reason; a restart marks interrupted ones failed too.

Workflow (`PackageWorkflow`, request transaction):

    generated -> reviewed -> approved -> submitted
         \\-----------\\---------\\--> rejected
    any non-final package -> regenerate (new version; the old one is superseded)

Approval creates or updates the job's `applications` row (status 'ready',
APPROVAL_MODE) with the package's resume, cover letter and score; that row is
what browser automation (a later phase) will work from. This module never
submits anything: 'submitted' is recorded only when the user says they applied.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.agent_5_job_scoring import score as rule_score
from app.agents.agent_6_resume_tailoring import (
    CandidateFacts,
    ResumeTailoringAgent,
    TailoringJob,
)
from app.agents.agent_7_resume_generation import (
    DOCX_TYPE,
    PDF_TYPE,
    render_letter_files,
    render_resume_files,
)
from app.agents.agent_8_cover_letters import (
    CoverLetterAgent,
    CoverLetterInput,
    CoverLetterResult,
    generation_json,
)
from app.agents.agent_9_application_answers import (
    AnswerJob,
    AnswerSettings,
    ApplicationAnswersAgent,
    GeneratedAnswer,
    generate_answers,
)
from app.agents.runs import track_agent_run
from app.core.exceptions import ConflictError, DomainValidationError, NotFoundError
from app.models.application import Application
from app.models.application_package import ApplicationPackage
from app.models.candidate_profile import CandidateProfile
from app.models.cover_letter import CoverLetter
from app.models.job import Job
from app.models.resume_version import ResumeVersion
from app.models.setting import Setting
from app.repositories.candidate_profile_repository import CandidateProfileRepository
from app.repositories.job_repository import JobRepository
from app.repositories.job_score_repository import JobScoreRepository
from app.repositories.package_repository import PackageRepository, PackageRow
from app.repositories.resume_repository import ResumeRepository, ResumeVersionRepository
from app.repositories.settings_repository import SettingsRepository
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
from app.services.scoring_service import job_input, preferences_input, profile_input
from app.storage import StorageBackend
from app.utils.hashing import hash_question

logger = logging.getLogger(__name__)

INTERRUPTED = "Interrupted by a restart; regenerate it."
MAX_ERROR_CHARS = 1000
REGENERATABLE = ("generated", "reviewed", "approved", "rejected", "failed")
EDITABLE = ("generated", "reviewed")
DOCS = ("resume", "cover-letter", "original-resume")


class PackageInputError(DomainValidationError):
    """Something the package needs is missing (profile, parsed resume, ...)."""


def _now() -> datetime:
    return datetime.now(UTC)


def candidate_facts(profile: CandidateProfile) -> CandidateFacts:
    return CandidateFacts(
        skills=tuple(profile.skills),
        seniority=profile.seniority,
        years_experience=float(profile.years_experience)
        if profile.years_experience is not None
        else None,
        roles=tuple(profile.primary_roles) or tuple(profile.related_roles),
    )


def tailoring_job(job: Job, company_name: str) -> TailoringJob:
    return TailoringJob(
        title=job.title,
        company_name=company_name,
        description=job.description,
        requirements=tuple(str(r) for r in job.requirements),
    )


def answer_settings(s: Setting) -> AnswerSettings:
    return AnswerSettings(
        salary_min=s.salary_min,
        salary_target=s.salary_target,
        salary_currency=s.salary_currency,
        willing_to_relocate=s.willing_to_relocate,
        requires_sponsorship=s.requires_sponsorship,
        work_authorization=s.work_authorization,
        visa_status=s.visa_status,
    )


def contact_line(profile: CandidateProfile) -> str:
    return "  |  ".join(x for x in (profile.email, profile.phone, profile.location) if x)


@dataclass
class _Inputs:
    package_id: uuid.UUID
    use_llm: bool
    include_cover_letter: bool
    job: Job
    company_name: str
    profile: CandidateProfile
    settings: Setting
    resume_id: uuid.UUID
    base_version: ResumeVersion
    score_snapshot: dict[str, Any]
    job_score_id: uuid.UUID | None


# ================================================================ generation
class PackageGenerator:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        storage: StorageBackend,
        tailoring: ResumeTailoringAgent,
        cover_letters: CoverLetterAgent,
        answers: ApplicationAnswersAgent,
    ) -> None:
        self.sessionmaker = sessionmaker
        self.storage = storage
        self.tailoring = tailoring
        self.cover_letters = cover_letters
        self.answers = answers

    async def generate(self, package_id: uuid.UUID) -> dict[str, Any]:
        try:
            async with track_agent_run(
                "application_package",
                input_summary={"package_id": str(package_id)},
                sessionmaker=self.sessionmaker,
            ) as run:
                summary = await self._generate(package_id)
                run.output_summary = summary
                return summary
        except Exception as exc:
            message = (
                exc.message
                if isinstance(exc, PackageInputError)
                else (f"{type(exc).__name__}: {exc}")
            )
            await self._fail(package_id, message)
            raise

    async def _fail(self, package_id: uuid.UUID, message: str) -> None:
        async with self.sessionmaker() as session, session.begin():
            pkg = await PackageRepository(session).lock(package_id)
            if pkg is not None and pkg.status == "generating":
                pkg.status, pkg.error = "failed", message[:MAX_ERROR_CHARS]

    async def _load(self, package_id: uuid.UUID) -> _Inputs:
        async with self.sessionmaker() as session, session.begin():
            pkg = await PackageRepository(session).get(package_id)
            if pkg is None:
                raise NotFoundError("Package not found", {"package_id": str(package_id)})
            if pkg.status != "generating":
                raise ConflictError(f"Package is {pkg.status}, not generating.")
            row = await JobRepository(session).get_with_company(pkg.job_id)
            if row is None:
                raise PackageInputError("The job no longer exists.")
            job, company_name, _ = row
            profile = await session.get(CandidateProfile, pkg.profile_id)
            if profile is None:
                raise PackageInputError("The profile no longer exists.")
            resume = await ResumeRepository(session).get_primary(profile.id)
            if resume is None:
                raise PackageInputError("Upload a resume first: the package is built from it.")
            base = await ResumeVersionRepository(session).latest(resume.id, "parsed")
            if base is None:
                raise PackageInputError("Your resume has not been parsed yet.")
            settings = await SettingsRepository(session).get_singleton()
            snapshot, score_id = await self._score(session, job, company_name, profile, settings)
            gen = dict(pkg.generation)
            return _Inputs(
                package_id,
                bool(gen.get("use_llm")),
                bool(gen.get("include_cover_letter", True)),
                job,
                company_name,
                profile,
                settings,
                resume.id,
                base,
                snapshot,
                score_id,
            )

    @staticmethod
    async def _score(
        session: AsyncSession, job: Job, company: str, profile: CandidateProfile, s: Setting
    ) -> tuple[dict[str, Any], uuid.UUID | None]:
        """The job's effective score (Claude when current, else rules); computed
        on the spot when the job has not been scored yet."""
        rows = await JobScoreRepository(session).for_job(job.id, profile.id)
        rules = next((r for r in rows if r.scoring_method == "rules"), None)
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
        if current is not None:
            return {
                "overall": current.overall_score,
                "method": current.scoring_method,
                "matched_skills": list(current.matched_skills),
                "missing_skills": list(current.missing_skills),
                "rationale": current.rationale,
                "interview_probability": current.interview_probability,
            }, current.id
        result = rule_score(job_input(job, company), profile_input(profile), preferences_input(s))
        return {
            "overall": result.overall,
            "method": "rules",
            "matched_skills": result.matched_skills,
            "missing_skills": result.missing_skills,
            "rationale": result.rationale,
            "computed_for_package": True,
        }, None

    async def _generate(self, package_id: uuid.UUID) -> dict[str, Any]:
        inp = await self._load(package_id)
        original = ParsedResume.model_validate(inp.base_version.content)
        cand = candidate_facts(inp.profile)
        tjob = tailoring_job(inp.job, inp.company_name)

        # Agents (no transaction open).
        tailored = await self.tailoring.run(original, tjob, cand, use_llm=inp.use_llm)
        letter: CoverLetterResult | None = None
        letter_input = CoverLetterInput(
            tailored.content,
            tjob,
            cand,
            tuple(tailored.matched_skills),
            sender_name=inp.profile.full_name,
            sender_contact=contact_line(inp.profile),
        )
        if inp.include_cover_letter:
            letter = await self.cover_letters.run(letter_input, use_llm=inp.use_llm)
        job = inp.job
        answers = generate_answers(
            tailored.content,
            cand,
            AnswerJob(
                tjob,
                job.location,
                job.remote_type,
                job.salary_min,
                job.salary_max,
                job.salary_currency,
            ),
            answer_settings(inp.settings),
            tailored.matched_skills,
            tailored.missing_skills,
            profile_location=inp.profile.location,
        )
        answer_notes = await self.answers.run(
            answers, tailored.content, cand, tjob, use_llm=inp.use_llm
        )

        # Files (Agent 7), written before the rows that point to them.
        tailored_id, letter_id = uuid.uuid4(), uuid.uuid4()
        tailored_paths = await self._store_resume(f"tailored-{tailored_id}", tailored.content)
        base_paths: tuple[str, str] | None = None
        if not (inp.base_version.pdf_path and inp.base_version.docx_path):
            base_paths = await self._store_resume(f"parsed-{inp.base_version.id}", original)
        letter_paths = None
        if letter is not None:
            files = await render_letter_files(letter.letter(letter_input))
            letter_paths = (
                f"generated/cover-letters/{letter_id}.pdf",
                f"generated/cover-letters/{letter_id}.docx",
            )
            await self.storage.put(letter_paths[0], files.pdf, PDF_TYPE)
            await self.storage.put(letter_paths[1], files.docx, DOCX_TYPE)

        # Rows, in one short transaction.
        async with self.sessionmaker() as session, session.begin():
            repo = PackageRepository(session)
            pkg = await repo.lock(package_id)
            if pkg is None or pkg.status != "generating":
                raise ConflictError("The package changed while it was being generated.")
            await ResumeRepository(session).lock(inp.resume_id)
            version = await ResumeVersionRepository(session).create_next(
                inp.resume_id,
                id=tailored_id,
                kind="tailored",
                source="tailoring",
                job_id=job.id,
                target_role=job.title,
                target_company=inp.company_name,
                content=tailored.content.model_dump(mode="json"),
                ats_keywords=tailored.matched_skills,
                change_summary=tailored.summary,
                base_version_id=inp.base_version.id,
                changes=tailored.changes,
                tailoring=tailored.tailoring_json(),
                pdf_path=tailored_paths[0],
                docx_path=tailored_paths[1],
            )
            if base_paths is not None:
                base = await session.get(ResumeVersion, inp.base_version.id)
                if base is not None:
                    base.pdf_path, base.docx_path = base_paths
            cover_id = None
            if letter is not None and letter_paths is not None:
                session.add(
                    CoverLetter(
                        id=letter_id,
                        job_id=job.id,
                        profile_id=inp.profile.id,
                        version_number=await repo.next_cover_letter_version(job.id, inp.profile.id),
                        content=letter.text,
                        word_count=letter.word_count,
                        method=letter.method,
                        model=letter.model,
                        generation=generation_json(letter),
                        pdf_path=letter_paths[0],
                        docx_path=letter_paths[1],
                    )
                )
                await session.flush()
                cover_id = letter_id
            await repo.add_answers([_answer_row(package_id, a) for a in answers])
            pkg.status = "generated"
            pkg.generated_at = _now()
            pkg.resume_version_id = version.id
            pkg.base_resume_version_id = inp.base_version.id
            pkg.cover_letter_id = cover_id
            pkg.job_score_id = inp.job_score_id
            pkg.score_snapshot = inp.score_snapshot
            pkg.generation = dict(pkg.generation) | {
                "llm_used": tailored.method == "claude"
                or (letter is not None and letter.method == "claude")
                or any(a.source == "llm" for a in answers),
                "tailoring_notes": tailored.notes,
                "cover_letter_notes": letter.notes if letter else [],
                "answer_notes": answer_notes,
                "changes": len(tailored.changes),
            }
        return {
            "package_id": str(package_id),
            "changes": len(tailored.changes),
            "tailoring_method": tailored.method,
            "cover_letter": letter.method if letter else None,
            "answers": len(answers),
            "answers_needing_review": sum(a.needs_review for a in answers),
        }

    async def _store_resume(self, stem: str, content: ParsedResume) -> tuple[str, str]:
        files = await render_resume_files(content)
        paths = (f"generated/resume-versions/{stem}.pdf", f"generated/resume-versions/{stem}.docx")
        await self.storage.put(paths[0], files.pdf, PDF_TYPE)
        await self.storage.put(paths[1], files.docx, DOCX_TYPE)
        return paths


def _answer_row(package_id: uuid.UUID, a: GeneratedAnswer) -> dict[str, Any]:
    row = a.as_row()
    return row | {"package_id": package_id, "question_hash": hash_question(a.question)}


# ================================================================== workflow
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
            raise ConflictError(f"A {old.status} package cannot be regenerated.")
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
            pkg.status, pkg.reviewed_at = "reviewed", _now()
        elif pkg.status not in ("reviewed", "approved", "submitted"):
            raise ConflictError(f"A {pkg.status} package cannot be marked reviewed.")
        return pkg

    async def approve(self, package_id: uuid.UUID, notes: str | None) -> ApplicationPackage:
        pkg = await self._lock(package_id)
        if pkg.status not in ("generated", "reviewed"):
            raise ConflictError(f"A {pkg.status} package cannot be approved.")
        if pkg.resume_version_id is None:
            raise ConflictError("The package has no tailored resume (was it deleted?).")
        now = _now()
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
            raise ConflictError(f"A {pkg.status} package cannot be rejected.")
        await self._withdraw_approval(pkg, f"Package rejected: {reason}")
        pkg.status, pkg.rejected_at, pkg.rejection_reason = "rejected", _now(), reason
        await self.session.flush()
        return pkg

    async def mark_submitted(self, package_id: uuid.UUID) -> ApplicationPackage:
        """Record that the user applied with this package (nothing is sent)."""
        pkg = await self._lock(package_id)
        if pkg.status != "approved":
            raise ConflictError("Only an approved package can be marked as submitted.")
        now = _now()
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
            app.status, app.approved_at, app.status_updated_at = "drafted", None, _now()
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
