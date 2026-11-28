"""Agent runs (agent_runs): the activity log of every agent and pipeline stage."""

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from typing import NamedTuple

from sqlalchemy import Select, func, select

from app.models.agent_run import AgentRun
from app.repositories.base import Repository


class AgentStats(NamedTuple):
    agent_name: str
    runs: int
    succeeded: int
    failed: int
    running: int
    input_tokens: int
    output_tokens: int
    cost_usd: Decimal
    avg_duration_ms: float | None
    last_run_at: datetime | None


class AgentRunRepository(Repository[AgentRun]):
    model = AgentRun

    def _filtered(
        self, agent_name: str | None, status: str | None, since: datetime | None
    ) -> Select[AgentRun]:
        stmt = select(AgentRun)
        if agent_name:
            stmt = stmt.where(AgentRun.agent_name == agent_name)
        if status:
            stmt = stmt.where(AgentRun.status == status)
        if since:
            stmt = stmt.where(AgentRun.started_at >= since)
        return stmt

    async def search(
        self,
        *,
        agent_name: str | None = None,
        status: str | None = None,
        since: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[Sequence[AgentRun], int]:
        stmt = self._filtered(agent_name, status, since)
        total = await self.count(stmt)
        rows = await self.list_page(
            query=stmt.order_by(AgentRun.started_at.desc(), AgentRun.id), limit=limit, offset=offset
        )
        return rows, total

    async def stats(self, *, since: datetime | None = None) -> list[AgentStats]:
        """Per agent: run counts by outcome, tokens, cost, average duration, last run."""
        stmt = (
            select(
                AgentRun.agent_name,
                func.count(),
                func.count().filter(AgentRun.status == "succeeded"),
                func.count().filter(AgentRun.status == "failed"),
                func.count().filter(AgentRun.status == "running"),
                func.coalesce(func.sum(AgentRun.input_tokens), 0),
                func.coalesce(func.sum(AgentRun.output_tokens), 0),
                func.coalesce(func.sum(AgentRun.cost_usd), 0),
                func.avg(AgentRun.duration_ms),
                func.max(AgentRun.started_at),
            )
            .group_by(AgentRun.agent_name)
            .order_by(AgentRun.agent_name)
        )
        if since:
            stmt = stmt.where(AgentRun.started_at >= since)
        rows = (await self.session.execute(stmt)).all()
        return [
            AgentStats(
                agent_name=r[0],
                runs=int(r[1]),
                succeeded=int(r[2]),
                failed=int(r[3]),
                running=int(r[4]),
                input_tokens=int(r[5]),
                output_tokens=int(r[6]),
                cost_usd=Decimal(r[7]),
                avg_duration_ms=float(r[8]) if r[8] is not None else None,
                last_run_at=r[9],
            )
            for r in rows
        ]

    async def agent_names(self) -> list[str]:
        stmt = select(AgentRun.agent_name).distinct().order_by(AgentRun.agent_name)
        return list((await self.session.scalars(stmt)).all())
