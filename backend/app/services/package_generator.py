"""Application package generation (background task, own short transactions).

    Candidate profile + primary resume (latest parsed version) + job + score
      -> Agent 6 tailored resume (every change with its reason)
      -> Agent 7 PDF/DOCX of the original and the tailored resume
      -> Agent 8 cover letter (optional) + PDF/DOCX
      -> Agent 9 answers to common application questions
      -> one `application_packages` row linking them, status 'generated'

No transaction is open while agents or Claude run. Files are written before
the rows that point to them. A failure marks the package 'failed' with the
reason; a restart marks interrupted ones failed too (scheduler/tasks.py).
The state changes that follow are in `package_workflow`.
"""

import logging
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.agent_5_job_scoring import score as rule_score
from app.agents.agent_6_resume_tailoring import (
    ResumeTailoringAgent,
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
    ApplicationAnswersAgent,
    GeneratedAnswer,
    generate_answers,
)
from app.agents.runs import track_agent_run
from app.core.exceptions import ConflictError, NotFoundError
from app.models.candidate_profile import CandidateProfile
from app.models.cover_letter import CoverLetter
from app.models.job import Job
from app.models.resume_version import ResumeVersion
from app.models.setting import Setting
from app.repositories.job_repository import JobRepository
from app.repositories.job_score_repository import JobScoreRepository
from app.repositories.package_repository import PackageRepository
from app.repositories.resume_repository import ResumeRepository, ResumeVersionRepository
from app.repositories.settings_repository import SettingsRepository
from app.schemas.parsed_resume import ParsedResume
from app.services.package_inputs import (
    PackageInputError,
    answer_settings,
    candidate_facts,
    contact_line,
    tailoring_job,
    utcnow,
)
from app.services.scoring_service import job_input, preferences_input, profile_input
from app.storage import StorageBackend
from app.utils.hashing import hash_question

logger = logging.getLogger(__name__)

MAX_ERROR_CHARS = 1000


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
            pkg.generated_at = utcnow()
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
