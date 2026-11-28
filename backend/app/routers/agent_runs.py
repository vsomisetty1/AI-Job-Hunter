"""Agent activity: every agent invocation and pipeline stage (agent_runs), with
its outcome, timing, tokens and cost. Read-only."""

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Query

from app.dependencies import DbSession
from app.repositories.agent_run_repository import AgentRunRepository
from app.schemas.agent_run import (
    AgentActivitySummary,
    AgentRunRead,
    AgentRunStatus,
    AgentStat,
)
from app.schemas.common import ERROR_RESPONSES, Page, PaginationParams

router = APIRouter(prefix="/agent-runs", tags=["agent-runs"], responses=ERROR_RESPONSES)


@router.get("", response_model=Page[AgentRunRead], summary="Agent runs, newest first")
async def list_runs(
    db: DbSession,
    page: Annotated[PaginationParams, Query()],
    agent: Annotated[str | None, Query(max_length=100, description="Agent name")] = None,
    status: Annotated[AgentRunStatus | None, Query()] = None,
) -> Page[AgentRunRead]:
    rows, total = await AgentRunRepository(db).search(
        agent_name=agent, status=status, limit=page.limit, offset=page.offset
    )
    return Page[AgentRunRead](
        items=[AgentRunRead.model_validate(r) for r in rows],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get(
    "/summary",
    response_model=AgentActivitySummary,
    summary="Runs, failures, tokens and cost per agent over the last `days` days",
)
async def summary(
    db: DbSession, days: Annotated[int, Query(ge=1, le=365)] = 30
) -> AgentActivitySummary:
    since = datetime.now(UTC) - timedelta(days=days)
    stats = await AgentRunRepository(db).stats(since=since)
    agents = [
        AgentStat(**s._asdict() | {"cost_usd": float(s.cost_usd)})  # Decimal -> JSON number
        for s in stats
    ]
    return AgentActivitySummary(
        days=days,
        agents=agents,
        total_runs=sum(a.runs for a in agents),
        failed_runs=sum(a.failed for a in agents),
        total_cost_usd=round(sum(a.cost_usd for a in agents), 6),
    )


@router.get("/agents", response_model=list[str], summary="Names of agents that have run")
async def agent_names(db: DbSession) -> list[str]:
    return await AgentRunRepository(db).agent_names()
