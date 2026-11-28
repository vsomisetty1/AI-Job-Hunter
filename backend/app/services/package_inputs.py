"""Package inputs: how stored rows become the agents' inputs.

Shared by generation (`package_generator`) and the workflow (`package_workflow`).
"""

from datetime import UTC, datetime

from app.agents.agent_6_resume_tailoring import (
    CandidateFacts,
    TailoringJob,
)
from app.agents.agent_9_application_answers import (
    AnswerSettings,
)
from app.core.exceptions import DomainValidationError
from app.models.candidate_profile import CandidateProfile
from app.models.job import Job
from app.models.setting import Setting


class PackageInputError(DomainValidationError):
    """Something the package needs is missing (profile, parsed resume, ...)."""


def utcnow() -> datetime:
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
