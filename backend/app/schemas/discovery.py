"""Discovery API schemas: runs, start requests, connector health, suggestions."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.common import APIModel, ORMModel
from app.schemas.job import Source

RunStatus = Literal["running", "succeeded", "partial", "failed", "cancelled"]


class DiscoveryRunSummary(ORMModel):
    id: uuid.UUID
    trigger: Literal["manual", "scheduled"]
    status: RunStatus
    companies_total: int
    companies_succeeded: int
    companies_failed: int
    jobs_found: int
    jobs_inserted: int
    jobs_updated: int
    jobs_unchanged: int
    jobs_skipped: int
    jobs_expired: int
    error: str | None
    started_at: datetime
    finished_at: datetime | None
    duration_ms: int | None


class DiscoveryRunDetail(DiscoveryRunSummary):
    # One entry per company: counts, status, error, skip reasons, invalid samples.
    details: list[dict[str, Any]]


class StartDiscoveryRequest(APIModel):
    company_ids: list[uuid.UUID] | None = Field(
        default=None,
        max_length=500,
        description="Crawl only these companies (default: all tracked).",
    )
    only_due: bool = Field(
        default=False, description="Incremental: skip companies crawled within the interval."
    )


class DiscoveryStarted(BaseModel):
    run_id: uuid.UUID
    task_id: str
    status: str
    detail: str


class ConnectorProbe(BaseModel):
    source: str
    ok: bool
    board: str
    latency_ms: int
    jobs_visible: int | None
    error: str | None


class SourceHealth(BaseModel):
    source: str
    display_name: str
    companies_tracked: int
    companies_failing: int
    last_success_at: datetime | None
    jobs_active: int
    probe: ConnectorProbe | None


class DirectoryEntryRead(BaseModel):
    source: Source
    slug: str
    name: str
    added: bool


class BoardKey(APIModel):
    source: Source
    slug: str = Field(min_length=1, max_length=100)


class AddSuggestedRequest(APIModel):
    boards: list[BoardKey] = Field(min_length=1, max_length=100)
