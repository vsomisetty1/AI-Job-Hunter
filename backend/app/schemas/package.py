"""Application package schemas: Claude outputs for Agents 6, 8 and 9, and the API."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import APIModel, ORMModel
from app.schemas.job import JobSummary
from app.schemas.parsed_resume import ParsedResume

PackageStatus = Literal[
    "generating", "generated", "reviewed", "approved", "rejected", "submitted", "failed",
    "superseded",
]  # fmt: skip


class _Out(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)


# ------------------------------------------------------------- Claude outputs
class BulletRewrite(_Out):
    role: int = Field(description="0-based index of the role in experience")
    index: int = Field(description="0-based index of the bullet within that role")
    text: str = Field(description="The reworded bullet")
    reason: str = Field(description="One short sentence: what the rewording emphasises")


class TailoringRewriteOutput(_Out):
    summary: str | None = Field(
        default=None, description="Reworded summary, or null to keep the current one"
    )
    summary_reason: str | None = None
    bullets: list[BulletRewrite] = Field(
        default_factory=list, description="Only bullets worth rewording; at most 12"
    )


class CoverLetterOutput(_Out):
    paragraphs: list[str] = Field(description="3-4 body paragraphs, no greeting or sign-off")


class AnswerRewrite(_Out):
    key: str = Field(description="The question key it answers")
    answer: str


class AnswersRewriteOutput(_Out):
    answers: list[AnswerRewrite]


# ------------------------------------------------------------------ API
class ResumeChange(BaseModel):
    section: str
    item: str | None = None
    field: str
    before: Any = None
    after: Any = None
    reason: str
    at: datetime


class TailoredResumeRead(ORMModel):
    id: uuid.UUID
    resume_id: uuid.UUID
    version_number: int
    base_version_id: uuid.UUID | None
    content: ParsedResume
    changes: list[ResumeChange]
    tailoring: dict[str, Any]
    ats_keywords: list[str]
    change_summary: str | None
    has_pdf: bool = False
    has_docx: bool = False
    created_at: datetime


class CoverLetterRead(ORMModel):
    id: uuid.UUID
    version_number: int
    content: str
    word_count: int
    method: Literal["rules", "claude"]
    model: str | None
    generation: dict[str, Any]
    has_pdf: bool = False
    has_docx: bool = False
    created_at: datetime


class AnswerRead(ORMModel):
    id: uuid.UUID
    question: str
    question_key: str | None
    answer: str
    source: Literal["profile", "settings", "rules", "llm", "user"]
    confidence: float | None
    needs_review: bool
    evidence: list[dict[str, Any]]
    updated_at: datetime


class PackageSummary(BaseModel):
    id: uuid.UUID
    job_id: uuid.UUID
    job_title: str
    company_name: str
    version_number: int
    status: PackageStatus
    score: int | None
    score_method: str | None
    answers_needing_review: int = 0
    error: str | None
    generated_at: datetime | None
    reviewed_at: datetime | None
    approved_at: datetime | None
    rejected_at: datetime | None
    submitted_at: datetime | None
    created_at: datetime
    updated_at: datetime


class PackageDetail(PackageSummary):
    job: JobSummary
    score_snapshot: dict[str, Any]
    generation: dict[str, Any]
    review_notes: str | None
    rejection_reason: str | None
    application_id: uuid.UUID | None
    base_resume: ParsedResume | None
    base_resume_version_id: uuid.UUID | None
    tailored_resume: TailoredResumeRead | None
    cover_letter: CoverLetterRead | None
    answers: list[AnswerRead]


class GeneratePackageRequest(APIModel):
    job_id: uuid.UUID
    use_llm: bool = Field(
        default=False,
        description="Also let Claude reword (needs ANTHROPIC_API_KEY; checked against your resume)",
    )
    include_cover_letter: bool = True


class RegeneratePackageRequest(APIModel):
    use_llm: bool = False
    include_cover_letter: bool = True


class ApprovePackageRequest(APIModel):
    notes: str | None = Field(default=None, max_length=2000)


class RejectPackageRequest(APIModel):
    reason: str = Field(min_length=1, max_length=2000)


class AnswerUpdate(APIModel):
    answer: str = Field(min_length=1, max_length=5000)


class PackageStarted(BaseModel):
    package_id: uuid.UUID
    task_id: str
    status: str
    detail: str
