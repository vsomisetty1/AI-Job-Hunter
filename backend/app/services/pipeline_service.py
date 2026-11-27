"""Discover -> Score -> Tailor -> Apply orchestration.

`PipelineService` runs stages in order, passing a shared context dict, and
stops at the first failure. Each stage is recorded in agent_runs through
`app.agents.runs.track_agent_run`. Stages are plugged in by Phases 5-7.
"""

import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.runs import AgentRunHandle, track_agent_run

logger = logging.getLogger(__name__)


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
