"""Candidate profile: stored structure, Claude outputs, and API schemas."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

from app.schemas.common import APIModel
from app.schemas.parsed_resume import (
    AwardEntry,
    CertificationEntry,
    EducationEntry,
    ProjectEntry,
    PublicationEntry,
    SkillGroup,
)

Seniority = Literal[
    "intern", "entry", "junior", "mid", "senior", "staff", "principal",
    "lead", "manager", "director", "executive",
]  # fmt: skip
Trajectory = Literal["early_career", "ascending", "lateral", "pivoting", "mixed", "returning"]
ExperienceLevel = Literal["entry", "mid", "senior", "expert"]

EDITABLE_FIELDS = (
    "full_name", "email", "phone", "location", "linkedin_url", "portfolio_url", "headline",
    "summary", "seniority", "years_of_experience", "skills", "industries", "inferred_roles",
    "transferable_roles", "education_summary", "certification_summary",
)  # fmt: skip


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)


# ------------------------------------------------------------- Claude outputs
class RoleSuggestion(_Model):
    title: str
    rationale: str = Field(description="One sentence: why this candidate fits the role")


class ProfileInferenceOutput(_Model):
    headline: str = Field(description="One-line professional headline, max ~12 words")
    seniority: Seniority
    seniority_rationale: str = Field(description="One sentence")
    inferred_roles: list[str] = Field(
        description="3-6 job titles the candidate is qualified for today, most suitable first"
    )
    transferable_roles: list[RoleSuggestion] = Field(
        description="2-5 adjacent roles reachable with existing skills (not repeats of the above)"
    )
    industries: list[str] = Field(description="Industries the candidate has worked in")
    education_summary: str = Field(description="One sentence, or empty if no education listed")
    certification_summary: str = Field(description="One sentence, or empty if none")


class CareerAnalysisOutput(_Model):
    narrative: str = Field(description="2-3 sentences describing the career story")
    trajectory: Trajectory
    strengths: list[str] = Field(description="3-5 concrete strengths backed by the resume")
    gaps: list[str] = Field(description="0-4 gaps or risks a recruiter might notice")
    recommended_focus: list[str] = Field(description="2-4 actionable suggestions for the search")


class SkillExtractionOutput(_Model):
    technical: list[str] = Field(description="Programming languages, frameworks, methods")
    tools: list[str] = Field(description="Products, platforms and tools")
    domains: list[str] = Field(description="Business or technical domains")
    soft_skills: list[str] = Field(description="Only those evidenced by achievements")


# ------------------------------------------------------- stored profile data
class CareerHistoryItem(_Model):
    title: str | None = None
    company: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    is_current: bool = False
    duration_months: int | None = None


class ProfileData(_Model):
    """candidate_profiles.profile (JSONB)."""

    headline: str | None = None
    summary: str | None = None
    career_history: list[CareerHistoryItem] = Field(default_factory=list)
    skill_groups: list[SkillGroup] = Field(default_factory=list)
    education: list[EducationEntry] = Field(default_factory=list)
    education_summary: str | None = None
    certifications: list[CertificationEntry] = Field(default_factory=list)
    certification_summary: str | None = None
    projects: list[ProjectEntry] = Field(default_factory=list)
    publications: list[PublicationEntry] = Field(default_factory=list)
    awards: list[AwardEntry] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    source_resume_id: str | None = None
    source_version_id: str | None = None


class InferenceData(_Model):
    """candidate_profiles.inference (JSONB)."""

    source: Literal["deterministic", "llm"] = "deterministic"
    model: str | None = None
    seniority_rationale: str | None = None
    transferable_roles: list[RoleSuggestion] = Field(default_factory=list)
    career_analysis: CareerAnalysisOutput | None = None
    extracted_skills: SkillExtractionOutput | None = None
    warnings: list[str] = Field(default_factory=list)
    # Fields the user edited by hand; regeneration keeps them unless asked not to.
    overrides: list[str] = Field(default_factory=list)


# ------------------------------------------------------------------- API
class CandidateProfileRead(BaseModel):
    id: uuid.UUID
    full_name: str
    email: str | None
    phone: str | None
    location: str | None
    linkedin_url: str | None
    portfolio_url: str | None
    headline: str | None
    summary: str | None
    seniority: str | None
    experience_level: str | None
    years_of_experience: float | None
    skills: list[str]
    skill_groups: list[SkillGroup]
    industries: list[str]
    inferred_roles: list[str]
    transferable_roles: list[RoleSuggestion]
    career_history: list[CareerHistoryItem]
    education: list[EducationEntry]
    education_summary: str | None
    certifications: list[CertificationEntry]
    certification_summary: str | None
    projects: list[ProjectEntry]
    publications: list[PublicationEntry]
    awards: list[AwardEntry]
    languages: list[str]
    career_analysis: CareerAnalysisOutput | None
    inference_source: str
    inference_model: str | None
    inference_status: str
    inference_error: str | None
    inferred_at: datetime | None
    overrides: list[str]
    warnings: list[str]
    source_resume_id: str | None
    updated_at: datetime


def _clean_str_list(values: list[str], max_items: int, max_len: int = 120) -> list[str]:
    out: dict[str, str] = {}
    for v in values:
        v = " ".join(v.split())
        if not v:
            continue
        if len(v) > max_len:
            raise ValueError(f"entries must be at most {max_len} characters")
        out.setdefault(v.casefold(), v)
    if len(out) > max_items:
        raise ValueError(f"at most {max_items} entries")
    return list(out.values())


class CandidateProfileUpdate(APIModel):
    """PATCH body. Edited fields are remembered as overrides."""

    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    email: str | None = Field(default=None, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    phone: str | None = Field(default=None, max_length=50)
    location: str | None = Field(default=None, max_length=200)
    linkedin_url: HttpUrl | None = None
    portfolio_url: HttpUrl | None = None
    headline: str | None = Field(default=None, max_length=300)
    summary: str | None = Field(default=None, max_length=5000)
    seniority: Seniority | None = None
    years_of_experience: Decimal | None = Field(default=None, ge=0, le=70, decimal_places=1)
    skills: list[str] | None = None
    industries: list[str] | None = None
    inferred_roles: list[str] | None = None
    transferable_roles: list[RoleSuggestion] | None = Field(default=None, max_length=20)
    education_summary: str | None = Field(default=None, max_length=1000)
    certification_summary: str | None = Field(default=None, max_length=1000)

    @field_validator("skills")
    @classmethod
    def _skills(cls, v: list[str] | None) -> list[str] | None:
        return None if v is None else _clean_str_list(v, 300, 80)

    @field_validator("industries", "inferred_roles")
    @classmethod
    def _lists(cls, v: list[str] | None) -> list[str] | None:
        return None if v is None else _clean_str_list(v, 30)

    def changes(self) -> dict[str, object]:
        data = self.model_dump(exclude_unset=True, mode="json")
        if "full_name" in data and data["full_name"] is None:
            raise ValueError("full_name cannot be null")
        return data


class RegenerateProfileRequest(APIModel):
    resume_id: uuid.UUID | None = Field(
        default=None, description="Resume to build from; defaults to the primary resume"
    )
    keep_overrides: bool = Field(
        default=True, description="Keep fields you edited by hand instead of regenerating them"
    )
    use_llm: bool = Field(default=True, description="Use Claude when it is configured")


class TaskAccepted(BaseModel):
    task_id: str
    status: str
    detail: str


def experience_level(years: Decimal | float | None) -> ExperienceLevel | None:
    if years is None:
        return None
    y = float(years)
    return "entry" if y < 2 else "mid" if y < 5 else "senior" if y < 10 else "expert"
