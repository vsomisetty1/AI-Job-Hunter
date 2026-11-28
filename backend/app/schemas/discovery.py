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


class CompanyRunOutcome(BaseModel):
    """One company's result in a discovery run (discovery_runs.details)."""

    company_id: uuid.UUID
    source: Source
    slug: str
    name: str
    status: Literal["ok", "error", "not_found"] = "ok"
    found: int = 0
    invalid: int = 0
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    skipped: int = 0
    expired: int = 0
    pages: int = 0
    duration_ms: int = 0
    error: str | None = None
    notes: list[str] = Field(default_factory=list)
    skip_reasons: dict[str, int] = Field(default_factory=dict)
    invalid_samples: list[dict[str, Any]] = Field(default_factory=list)


class DiscoveryRunDetail(DiscoveryRunSummary):
    details: list[CompanyRunOutcome]


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
    source: Source
    ok: bool
    board: str
    latency_ms: int
    jobs_visible: int | None
    error: str | None


class SourceHealth(BaseModel):
    source: Source
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
