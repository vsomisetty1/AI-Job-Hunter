"""What an application form may be filled with: the applicant's facts and files,
taken from the approved package only (tailored resume, profile, settings, and
package answers that are usable: reviewed, or written by the user)."""

import logging
import re

from sqlalchemy.ext.asyncio import AsyncSession

from app.automation.field_matcher import AnswerFact, ApplicantFacts
from app.automation.form_engine import FilePayload
from app.models.application_answer import ApplicationAnswer
from app.models.application_package import ApplicationPackage
from app.models.candidate_profile import CandidateProfile
from app.models.cover_letter import CoverLetter
from app.models.resume_version import ResumeVersion
from app.models.setting import Setting
from app.repositories.package_repository import PackageRepository
from app.schemas.parsed_resume import ParsedResume
from app.storage import StorageBackend

logger = logging.getLogger(__name__)

_US_STATE = re.compile(
    r"\b(A[LKZR]|C[AOT]|D[EC]|FL|GA|HI|I[ADLN]|K[SY]|LA|M[ADEINOST]|N[CDEHJMVY]|O[HKR]|PA|RI|"
    r"S[CD]|T[NX]|UT|V[AT]|W[AIVY])\b|\b(USA|U\.S\.A?\.?|United States)\b"
)


def country_from(location: str | None) -> str | None:
    """The country a free-text location is in, when it is obvious (US only)."""
    if location and _US_STATE.search(location):
        return "United States"
    return None


def _split_name(name: str | None) -> tuple[str | None, str | None]:
    parts = (name or "").split()
    if len(parts) < 2:
        return (parts[0] if parts else None), None
    return parts[0], parts[-1]


_MONTHS = (
    "January", "February", "March", "April", "May", "June", "July", "August", "September",
    "October", "November", "December",
)  # fmt: skip


def _year_month(date: str | None) -> tuple[str | None, str | None]:
    """'2022-08' -> ('2022', 'August')."""
    m = re.match(r"^(\d{4})(?:-(\d{2}))?", date or "")
    if not m:
        return None, None
    month = _MONTHS[int(m.group(2)) - 1] if m.group(2) and 1 <= int(m.group(2)) <= 12 else None
    return m.group(1), month


def _file_name(name: str | None, doc: str) -> str:
    base = "_".join(re.findall(r"[A-Za-z0-9]+", name or "")) or "Applicant"
    return f"{base}_{doc}.pdf"


async def applicant_facts(
    session: AsyncSession, storage: StorageBackend, pkg: ApplicationPackage
) -> tuple[ApplicantFacts, dict[str, FilePayload]]:
    """Everything the form may use, from the approved package only."""
    version = (
        await session.get(ResumeVersion, pkg.resume_version_id) if pkg.resume_version_id else None
    )
    resume = ParsedResume.model_validate(version.content) if version else ParsedResume()
    profile = await session.get(CandidateProfile, pkg.profile_id)
    letter = await session.get(CoverLetter, pkg.cover_letter_id) if pkg.cover_letter_id else None
    setting = await session.get(Setting, 1)
    answers: list[ApplicationAnswer] = await PackageRepository(session).answers(pkg.id)
    contact = resume.contact
    name = contact.name or (profile.full_name if profile else None)
    first, last = _split_name(name)
    location = contact.location or (profile.location if profile else None)
    current = next((e for e in resume.experience if e.is_current), None) or (
        resume.experience[0] if resume.experience else None
    )
    years = profile.years_experience if profile else None
    school = max(resume.education, key=lambda e: e.end_date or "", default=None)
    grad_year, grad_month = _year_month(school.end_date if school else None)
    facts = ApplicantFacts(
        full_name=name,
        first_name=first,
        last_name=last,
        email=contact.email or (profile.email if profile else None),
        phone=contact.phone or (profile.phone if profile else None),
        location=location,
        country=country_from(location),
        linkedin=str(contact.linkedin) if contact.linkedin else None,
        github=str(contact.github) if contact.github else None,
        website=str(contact.portfolio) if contact.portfolio else None,
        current_company=current.company if current else None,
        current_title=current.title if current else None,
        years_experience=int(years) if years is not None else None,
        salary_target=setting.salary_target if setting else None,
        salary_currency=setting.salary_currency if setting else "USD",
        school=school.institution if school else None,
        degree=school.degree if school else None,
        discipline=school.field_of_study if school else None,
        grad_year=grad_year,
        grad_month=grad_month,
        answers=tuple(
            AnswerFact(
                key=a.question_key or "",
                question=a.question,
                answer=a.answer,
                usable=(not a.needs_review) or a.source == "user",
            )
            for a in answers
        ),
        has_resume_file=bool(version and version.pdf_path),
        has_cover_letter_file=bool(letter and letter.pdf_path),
        cover_letter_text=letter.content if letter else None,
    )
    files: dict[str, FilePayload] = {}
    if version and version.pdf_path:
        files["resume"] = FilePayload(
            _file_name(name, "Resume"), "application/pdf",
            await storage.get(version.pdf_path),
        )  # fmt: skip
    if letter and letter.pdf_path:
        files["cover_letter"] = FilePayload(
            _file_name(name, "Cover_Letter"), "application/pdf",
            await storage.get(letter.pdf_path),
        )  # fmt: skip
    return facts, files
