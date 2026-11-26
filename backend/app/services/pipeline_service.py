"""Discover -> Score -> Tailor -> Apply orchestration.

Phase 3 provides the framework; the agents themselves are plugged in as
stages by Phases 4-7.

* `track_agent_run` writes one `agent_runs` row per agent invocation. It uses
  its OWN short transactions, so a failed run is still recorded when the
  caller's unit of work rolls back.
* `PipelineService` runs stages in order, passing a shared context dict,
  and stops at the first failure.
"""

import asyncio
import logging
import time
import uuid
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Protocol

from sqlalchemy import func, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.database import get_sessionmaker
from app.models.agent_run import AgentRun

logger = logging.getLogger(__name__)

_MAX_ERROR_CHARS = 4000


@dataclass
class AgentRunHandle:
    """Mutable view of a running agent; fields are persisted when the run ends."""

    id: uuid.UUID
    agent_name: str
    output_summary: dict[str, Any] = field(default_factory=dict)
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: Decimal = Decimal("0")

    def add_usage(
        self, input_tokens: int = 0, output_tokens: int = 0, cost_usd: float | Decimal = 0
    ) -> None:
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.cost_usd += Decimal(str(cost_usd))


@asynccontextmanager
async def track_agent_run(
    agent_name: str,
    *,
    job_id: uuid.UUID | None = None,
    application_id: uuid.UUID | None = None,
    input_summary: dict[str, Any] | None = None,
    sessionmaker: async_sessionmaker[AsyncSession] | None = None,
) -> AsyncIterator[AgentRunHandle]:
    maker = sessionmaker or get_sessionmaker()
    async with maker() as session, session.begin():
        run = AgentRun(
            agent_name=agent_name,
            job_id=job_id,
            application_id=application_id,
            input_summary=input_summary or {},
        )
        session.add(run)
        await session.flush()
        run_id = run.id

    handle = AgentRunHandle(id=run_id, agent_name=agent_name)
    started = time.perf_counter()
    status, error = "succeeded", None
    try:
        yield handle
    except BaseException as exc:
        status = "cancelled" if _is_cancellation(exc) else "failed"
        error = f"{type(exc).__name__}: {exc}"[:_MAX_ERROR_CHARS]
        raise
    finally:
        async with maker() as session, session.begin():
            await session.execute(
                update(AgentRun)
                .where(AgentRun.id == run_id)
                .values(
                    status=status,
                    error=error,
                    output_summary=handle.output_summary,
                    input_tokens=handle.input_tokens,
                    output_tokens=handle.output_tokens,
                    cost_usd=handle.cost_usd,
                    # DB clock, so finished_at >= started_at always holds.
                    finished_at=func.clock_timestamp(),
                    duration_ms=int((time.perf_counter() - started) * 1000),
                )
            )
        logger.info("agent run %s: %s", agent_name, status, extra={"agent_run_id": str(run_id)})


def _is_cancellation(exc: BaseException) -> bool:
    return isinstance(exc, asyncio.CancelledError | KeyboardInterrupt)


class PipelineStage(Protocol):
    """A pipeline step. `run` reads/extends the shared context and returns an output summary."""

    name: str

    async def run(self, context: dict[str, Any], run: AgentRunHandle) -> dict[str, Any]: ...


@dataclass
class StageResult:
    name: str
    agent_run_id: uuid.UUID | None  # None if the run row itself could not be written
    ok: bool
    output: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass
class PipelineResult:
    stages: list[StageResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(s.ok for s in self.stages)


class PipelineService:
    def __init__(
        self,
        stages: Sequence[PipelineStage],
        sessionmaker: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self.stages = list(stages)
        self._sessionmaker = sessionmaker

    @classmethod
    def discovery(cls) -> PipelineService:
        """Discovery -> dedup -> rule filter -> scoring. Stages arrive in Phases 5-6."""
        return cls(stages=[])

    async def run(self, context: dict[str, Any]) -> PipelineResult:
        result = PipelineResult()
        for stage in self.stages:
            run: AgentRunHandle | None = None
            try:
                async with track_agent_run(
                    stage.name,
                    input_summary={"context_keys": sorted(context)},
                    sessionmaker=self._sessionmaker,
                ) as run:
                    output = await stage.run(context, run)
                    run.output_summary = output
                result.stages.append(StageResult(stage.name, run.id, True, output))
            except Exception as exc:  # noqa: BLE001 - recorded in agent_runs and result
                result.stages.append(
                    StageResult(
                        stage.name,
                        run.id if run else None,
                        False,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                )
                logger.warning("pipeline stopped at stage %s", stage.name)
                break
        return result
