"""Structured resume data: the parser's output, Claude's output for weak
sections, and what the user edits. One schema for all three.

Rules that keep it usable as a Claude structured-output schema:
* no free-form dicts (every object has fixed fields);
* no hard length limits (they would make a valid-but-long answer fail);
  API input limits are enforced separately (see `check_size_limits`).

Dates are strings: "YYYY-MM" or "YYYY", or null.
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

PARSER_VERSION = "1.0"

SectionName = Literal[
    "contact",
    "summary",
    "experience",
    "education",
    "skills",
    "certifications",
    "projects",
    "publications",
    "awards",
]


def is_http_url(value: str) -> bool:
    """Links are stored and shown only as http(s): never javascript:, data:, file:..."""
    return value.lower().startswith(("http://", "https://"))


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)


class ContactInfo(_Model):
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    location: str | None = None
    linkedin: str | None = Field(default=None, description="LinkedIn profile URL")
    github: str | None = Field(default=None, description="GitHub profile URL")
    portfolio: str | None = Field(default=None, description="Personal website / portfolio URL")
    other_links: list[str] = Field(default_factory=list)

    @field_validator("linkedin", "github", "portfolio")
    @classmethod
    def _http_only(cls, v: str | None) -> str | None:
        return v if v is None or is_http_url(v) else None

    @field_validator("other_links")
    @classmethod
    def _http_only_list(cls, v: list[str]) -> list[str]:
        return [u for u in v if is_http_url(u)]


class ExperienceEntry(_Model):
    title: str | None = None
    company: str | None = None
    location: str | None = None
    start_date: str | None = Field(default=None, description="YYYY-MM or YYYY")
    end_date: str | None = Field(default=None, description="YYYY-MM or YYYY; null if current")
    is_current: bool = False
    bullets: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list, description="Skills used in this role")


class EducationEntry(_Model):
    institution: str | None = None
    degree: str | None = Field(default=None, description="e.g. B.S., Master of Science, PhD")
    field_of_study: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    gpa: str | None = None
    honors: list[str] = Field(default_factory=list)


class CertificationEntry(_Model):
    name: str
    issuer: str | None = None
    date: str | None = None
    expires: str | None = None
    credential_id: str | None = None


class ProjectEntry(_Model):
    name: str
    description: str | None = None
    url: str | None = None

    @field_validator("url")
    @classmethod
    def _http_only(cls, v: str | None) -> str | None:
        return v if v is None or is_http_url(v) else None

    technologies: list[str] = Field(default_factory=list)
    bullets: list[str] = Field(default_factory=list)


class PublicationEntry(_Model):
    title: str
    venue: str | None = None
    date: str | None = None
    url: str | None = None

    @field_validator("url")
    @classmethod
    def _http_only(cls, v: str | None) -> str | None:
        return v if v is None or is_http_url(v) else None


class AwardEntry(_Model):
    title: str
    issuer: str | None = None
    date: str | None = None
    description: str | None = None


class SkillGroup(_Model):
    name: str
    skills: list[str] = Field(default_factory=list)


class OtherSection(_Model):
    title: str
    lines: list[str] = Field(default_factory=list)


class SectionScore(_Model):
    section: str
    score: float


class ParseMeta(_Model):
    method: Literal["deterministic", "llm_assisted", "user_edit"] = "deterministic"
    parser_version: str = PARSER_VERSION
    confidence: float = Field(default=0.0, description="0-1 overall extraction confidence")
    section_confidence: list[SectionScore] = Field(default_factory=list)
    llm_sections: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ParsedResume(_Model):
    contact: ContactInfo = Field(default_factory=ContactInfo)
    summary: str | None = None
    experience: list[ExperienceEntry] = Field(default_factory=list)
    education: list[EducationEntry] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list, description="All skills, deduplicated")
    skill_groups: list[SkillGroup] = Field(default_factory=list)
    certifications: list[CertificationEntry] = Field(default_factory=list)
    projects: list[ProjectEntry] = Field(default_factory=list)
    publications: list[PublicationEntry] = Field(default_factory=list)
    awards: list[AwardEntry] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list, description="Spoken languages")
    other_sections: list[OtherSection] = Field(default_factory=list)
    meta: ParseMeta = Field(default_factory=ParseMeta)


# ----------------------------------------------------------------------------
# Limits for user-submitted edits (the API accepts a whole ParsedResume).
# ----------------------------------------------------------------------------
MAX_STRING_CHARS = 5000
MAX_LIST_ITEMS = 300
MAX_TOTAL_CHARS = 200_000


def check_size_limits(data: Any) -> None:
    """Raise ValueError if any string, list or the whole document is oversized."""
    total = 0

    def walk(node: Any, path: str) -> None:
        nonlocal total
        if isinstance(node, str):
            if len(node) > MAX_STRING_CHARS:
                raise ValueError(f"{path}: text longer than {MAX_STRING_CHARS} characters")
            total += len(node)
        elif isinstance(node, list | tuple):
            if len(node) > MAX_LIST_ITEMS:
                raise ValueError(f"{path}: more than {MAX_LIST_ITEMS} items")
            for i, item in enumerate(node):
                walk(item, f"{path}[{i}]")
        elif isinstance(node, dict):
            for key, value in node.items():
                walk(value, f"{path}.{key}" if path else str(key))
        if total > MAX_TOTAL_CHARS:
            raise ValueError(f"resume data larger than {MAX_TOTAL_CHARS} characters")

    walk(data, "")
