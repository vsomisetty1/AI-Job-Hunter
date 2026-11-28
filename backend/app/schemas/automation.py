"""Application automation API (approval mode)."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.common import APIModel

SubmissionStatus = Literal[
    "queued", "in_progress", "waiting_for_review", "submitting", "submitted", "failed",
    "cancelled",
]  # fmt: skip
LogLevel = Literal["debug", "info", "warning", "error"]


class StartSubmissionRequest(APIModel):
    package_id: uuid.UUID


class SubmitRequest(APIModel):
    # Approval mode: the request must say so explicitly; there is no default.
    confirm: Literal[True] = Field(
        description="Must be true: you reviewed the filled form and want it submitted."
    )


class FieldEditRequest(APIModel):
    key: str = Field(min_length=1, max_length=500)
    value: FieldValue = Field(description="Text, an option label, or yes/no")


class SubmissionStarted(BaseModel):
    submission_id: uuid.UUID
    task_id: str | None
    status: SubmissionStatus
    detail: str


class Screenshot(BaseModel):
    index: int
    step: str
    label: str
    at: str | None = None


class SubmissionSummary(BaseModel):
    id: uuid.UUID
    application_id: uuid.UUID
    package_id: uuid.UUID | None
    job_id: uuid.UUID
    job_title: str
    company_name: str
    job_status: str
    platform: str
    apply_url: str
    mode: Literal["APPROVAL_MODE"]
    status: SubmissionStatus
    step: str
    attempts: int
    error: str | None
    error_kind: str | None
    # Whether the filled form is still open in the browser (needed to submit).
    live: bool
    ready: bool | None
    missing_count: int
    problem_count: int
    queued_at: datetime
    started_at: datetime | None
    review_ready_at: datetime | None
    confirmed_at: datetime | None
    submitted_at: datetime | None
    failed_at: datetime | None
    cancelled_at: datetime | None
    updated_at: datetime


FieldValue = str | bool | list[str]


class EditableField(BaseModel):
    """A field the user can change in review (from the run's checkpoint)."""

    key: str
    label: str
    kind: str
    required: bool
    status: str
    value: FieldValue
    reason: str
    options: list[str]
    edited: bool


class SubmissionDetail(SubmissionSummary):
    review: dict[str, Any]
    edits: dict[str, FieldValue]
    checkpoint: dict[str, Any]
    screenshots: list[Screenshot]
    confirmation_text: str | None
    recovery_hint: str | None
    editable_fields: list[EditableField]


class ReadyPackage(BaseModel):
    package_id: uuid.UUID
    application_id: uuid.UUID
    job_id: uuid.UUID
    job_title: str
    company_name: str
    platform: str
    supported: bool
    job_status: str
    approved_at: datetime | None
    last_failure: str | None = None


class AutomationQueue(BaseModel):
    ready: list[ReadyPackage]
    active: list[SubmissionSummary]
    needs_attention: list[SubmissionSummary]


class AutomationLogRead(BaseModel):
    id: uuid.UUID
    submission_id: uuid.UUID
    job_title: str
    company_name: str
    level: LogLevel
    step: str | None
    message: str
    detail: dict[str, Any]
    created_at: datetime


class AutomationStatus(BaseModel):
    enabled: bool
    mode: Literal["APPROVAL_MODE"]
    autonomous_available: bool
    headless: bool
    browser_running: bool
    open_sessions: int
    max_sessions: int
    session_idle_minutes: int
