"""Resume parsing fallback: extract only the sections the deterministic parser
could not read confidently (or the whole resume for unusual layouts)."""

from pydantic import BaseModel, ConfigDict, Field

from app.llm.prompts.base import UNTRUSTED_INPUT_NOTICE, PromptTemplate
from app.schemas.parsed_resume import (
    AwardEntry,
    CertificationEntry,
    ContactInfo,
    EducationEntry,
    ExperienceEntry,
    ProjectEntry,
    PublicationEntry,
)


class ResumeExtractionOutput(BaseModel):
    """Only the requested sections are filled; others stay null."""

    model_config = ConfigDict(extra="ignore")

    contact: ContactInfo | None = None
    summary: str | None = None
    experience: list[ExperienceEntry] | None = None
    education: list[EducationEntry] | None = None
    skills: list[str] | None = Field(default=None, description="Explicitly listed skills")
    certifications: list[CertificationEntry] | None = None
    projects: list[ProjectEntry] | None = None
    publications: list[PublicationEntry] | None = None
    awards: list[AwardEntry] | None = None


RESUME_PARSE = PromptTemplate(
    name="resume_parse",
    version="1",
    purpose="resume_parse",
    output_model=ResumeExtractionOutput,
    max_tokens=8000,
    system=(
        "You extract structured data from resumes. Copy facts exactly as written: do not "
        "rephrase bullets, merge roles, or guess missing values (use null). Dates are "
        '"YYYY-MM" when a month is given, "YYYY" when only a year is given; a role that '
        "is ongoing has is_current=true and end_date=null. Keep each experience bullet as "
        "one string without the bullet character.\n\n" + UNTRUSTED_INPUT_NOTICE
    ),
    user_template=(
        "Extract these sections and leave every other field null: $sections\n\n"
        "<resume>\n$text\n</resume>"
    ),
)
