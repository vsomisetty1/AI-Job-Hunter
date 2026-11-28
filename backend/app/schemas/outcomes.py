"""Interview and outcome tracking API (Phase 9)."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.common import APIModel, ORMModel

InterviewStage = Literal[
    "recruiter_response", "recruiter_screen", "phone_screen", "technical_interview",
    "hiring_manager_interview", "onsite", "final_round", "offer", "rejection", "withdrawal",
]  # fmt: skip
EventStatus = Literal["scheduled", "completed", "cancelled", "no_show"]
ApplicationStatus = Literal[
    "drafted", "ready", "submitted", "interview", "rejected", "offer", "withdrawn"
]


class InterviewEventCreate(APIModel):
    stage: InterviewStage
    status: EventStatus = "completed"
    occurred_at: datetime = Field(description="When it happened, or is scheduled for")
    notes: str | None = Field(default=None, max_length=4000)


class InterviewEventUpdate(APIModel):
    stage: InterviewStage | None = None
    status: EventStatus | None = None
    occurred_at: datetime | None = None
    notes: str | None = Field(default=None, max_length=4000)


class InterviewEventRead(ORMModel):
    id: uuid.UUID
    application_id: uuid.UUID
    stage: InterviewStage
    status: EventStatus
    occurred_at: datetime
    notes: str | None
    created_at: datetime
    updated_at: datetime


class PipelineItem(BaseModel):
    application_id: uuid.UUID
    job_id: uuid.UUID
    job_title: str
    company_id: uuid.UUID
    company_name: str
    industry: str | None
    platform: str
    package_id: uuid.UUID | None
    status: ApplicationStatus
    # The latest thing that happened (or is scheduled), e.g. "technical_interview".
    current_stage: InterviewStage | None
    next_scheduled: InterviewEventRead | None
    submitted_at: datetime | None
    responded_at: datetime | None
    first_interview_at: datetime | None
    offer_at: datetime | None
    rejected_at: datetime | None
    withdrawn_at: datetime | None
    days_since_submitted: int | None
    events: int


class TimelineEntry(BaseModel):
    at: datetime
    kind: str  # package_generated, package_approved, submitted, or an interview stage
    label: str
    application_id: uuid.UUID | None
    job_id: uuid.UUID
    job_title: str
    company_name: str
    status: EventStatus | None = None  # an interview event's status
    detail: dict[str, Any] = Field(default_factory=dict)


class ApplicationOutcomes(PipelineItem):
    interview_events: list[InterviewEventRead]
    timeline: list[TimelineEntry]
