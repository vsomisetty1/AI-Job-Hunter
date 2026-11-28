"""Agent activity schemas (agent_runs)."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

from app.schemas.common import ORMModel

AgentRunStatus = Literal["running", "succeeded", "failed", "cancelled"]


class AgentRunRead(ORMModel):
    id: uuid.UUID
    agent_name: str
    status: AgentRunStatus
    job_id: uuid.UUID | None
    application_id: uuid.UUID | None
    input_summary: dict[str, Any]
    output_summary: dict[str, Any]
    error: str | None
    input_tokens: int
    output_tokens: int
    cost_usd: float
    started_at: datetime
    finished_at: datetime | None
    duration_ms: int | None


class AgentStat(BaseModel):
    agent_name: str
    runs: int
    succeeded: int
    failed: int
    running: int
    input_tokens: int
    output_tokens: int
    cost_usd: float
    avg_duration_ms: float | None
    last_run_at: datetime | None


class AgentActivitySummary(BaseModel):
    """Totals over the period (`days`), per agent and overall."""

    days: int
    agents: list[AgentStat]
    total_runs: int
    failed_runs: int
    total_cost_usd: float
