"""Resume API schemas."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.schemas.common import APIModel, ORMModel
from app.schemas.parsed_resume import ParsedResume, check_size_limits

VersionKind = Literal["original", "parsed", "tailored"]


class ResumeVersionSummary(ORMModel):
    id: uuid.UUID
    version_number: int
    kind: VersionKind
    source: str
    job_id: uuid.UUID | None
    target_role: str | None
    target_company: str | None
    change_summary: str | None
    ats_keywords: list[str]
    created_at: datetime


class ResumeVersionRead(ResumeVersionSummary):
    content: dict[str, Any]


class ResumeRead(ORMModel):
    id: uuid.UUID
    filename: str
    file_type: Literal["pdf", "docx"]
    size_bytes: int
    is_primary: bool
    parse_status: Literal["pending", "parsed", "failed"]
    parse_method: str | None
    parse_error: str | None
    parsed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ResumeDetail(ResumeRead):
    parsed: ParsedResume | None = None
    parsed_version_id: uuid.UUID | None = None
    versions: list[ResumeVersionSummary] = Field(default_factory=list)


class UploadResponse(BaseModel):
    resume: ResumeDetail
    task_id: str | None = Field(
        default=None, description="Background task enriching the parse and building the profile"
    )


class _SizeLimited(APIModel):
    @model_validator(mode="before")
    @classmethod
    def _limits(cls, data: Any) -> Any:
        check_size_limits(data)
        return data


class ParsedResumeUpdate(_SizeLimited):
    """Replace the parsed data (creates a new 'parsed' version; history is kept)."""

    data: ParsedResume
    change_summary: str | None = Field(default=None, max_length=500)


class TailoredVersionCreate(_SizeLimited):
    target_role: str | None = Field(default=None, min_length=1, max_length=200)
    target_company: str | None = Field(default=None, min_length=1, max_length=200)
    job_id: uuid.UUID | None = None
    content: ParsedResume
    change_summary: str | None = Field(default=None, max_length=500)
    ats_keywords: list[str] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def _target(self) -> TailoredVersionCreate:
        if not (self.job_id or self.target_role):
            raise ValueError("a tailored version needs a job_id or a target_role")
        return self


class ReparseRequest(APIModel):
    use_llm: bool = Field(default=True, description="Use Claude for sections the parser finds hard")
