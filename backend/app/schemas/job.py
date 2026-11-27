"""Job schemas: the connector output contract and the API models."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import APIModel, ORMModel

RemoteType = Literal["remote", "hybrid", "onsite", "unknown"]
EmploymentType = Literal["full_time", "part_time", "contract", "temporary", "internship"]
JobStatus = Literal["new", "filtered", "scored", "shortlisted", "skipped", "applied", "expired"]
Source = Literal["greenhouse", "lever", "ashby"]


class NormalizedJob(BaseModel):
    """What every connector produces from one raw posting (source-agnostic)."""

    model_config = ConfigDict(frozen=True)

    source: str
    source_job_id: str
    company_name: str
    title: str
    location: str | None = None
    remote_type: RemoteType = "unknown"
    employment_type: EmploymentType | None = None
    salary_min: int | None = None  # whole currency units per year
    salary_max: int | None = None
    salary_currency: str | None = None
    compensation_text: str | None = None
    description: str = ""  # plain text (never HTML)
    requirements: list[str] = Field(default_factory=list)
    url: str
    apply_url: str | None = None
    posted_at: datetime | None = None
    raw: dict[str, Any] = Field(default_factory=dict, repr=False)


# ------------------------------------------------------------------ API
class CompanyRead(ORMModel):
    id: uuid.UUID
    name: str
    source: str
    slug: str
    careers_url: str | None
    is_tracked: bool
    last_crawled_at: datetime | None
    last_crawl_status: str | None
    last_error: str | None
    consecutive_failures: int
    created_at: datetime


class CompanyWithStats(CompanyRead):
    active_jobs: int = 0


class CompanyCreate(APIModel):
    source: Source
    slug: str = Field(
        min_length=1, max_length=100, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
        description="Board name in the job-board URL, e.g. 'stripe' in boards.greenhouse.io/stripe",
    )  # fmt: skip
    name: str | None = Field(
        default=None, max_length=200, description="Defaults to the board's name"
    )


class CompanyUpdate(APIModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    is_tracked: bool | None = None


class JobSummary(BaseModel):
    id: uuid.UUID
    company_id: uuid.UUID
    company_name: str
    source: str
    external_id: str
    title: str
    location: str | None
    remote_type: RemoteType
    employment_type: str | None
    salary_min: int | None
    salary_max: int | None
    salary_currency: str | None
    status: JobStatus
    url: str
    posted_at: datetime | None
    first_seen_at: datetime
    last_seen_at: datetime


class JobDetail(JobSummary):
    compensation_text: str | None
    description: str
    requirements: list[str]
    apply_url: str | None
    dedup_key: str
    expired_at: datetime | None
    updated_at: datetime


class JobSearchParams(BaseModel):
    q: str | None = Field(default=None, max_length=200)
    source: Source | None = None
    company_id: uuid.UUID | None = None
    remote_type: RemoteType | None = None
    status: JobStatus | None = None
    include_expired: bool = False
    sort: Literal["newest", "posted", "title", "company"] = "newest"
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0)
