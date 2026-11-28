"""Pipeline orchestration: Discovery -> Deduplication -> Filtering -> Scoring.

`PipelineService` runs stages in order, passing a shared context dict, and
stops at the first failure. Each stage is recorded in agent_runs through
`app.agents.runs.track_agent_run` (agent name = stage name, output summary =
what the stage returned).

`JobPipeline` wires the job stages:

* `run(trigger, ...)`: discovery (Agents 2 + 3 per company), the cross-board
  duplicate sweep, the rule filter (Agent 4) and scoring (Agent 5, rules then
  optional Claude). Used by the scheduler and by "run discovery now".
* `rescore()`: everything after discovery, for when settings or the profile
  change.

Runs are serialised by a lock (single process), so filtering and scoring
never interleave with each other. Phase 7 adds tailoring and applying.
"""

import asyncio
import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.runs import AgentRunHandle, track_agent_run
from app.services.discovery_service import DiscoveryService
from app.services.filtering_service import FilteringService
from app.services.scoring_service import ScoringService

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


# ------------------------------------------------------------------ job stages
class DiscoveryStage:
    """Crawl boards (deduplicating within each company) for an existing run row."""

    name = "job_discovery"

    def __init__(self, discovery: DiscoveryService) -> None:
        self.discovery = discovery

    async def run(self, context: dict[str, Any], run: AgentRunHandle) -> dict[str, Any]:
        summary = await self.discovery.execute(
            context["discovery_run_id"],
            company_ids=context.get("company_ids"),
            only_due=context.get("only_due", False),
        )
        context["discovery"] = summary
        return {k: v for k, v in summary.items() if k != "details"}


class DeduplicationStage:
    name = "agent_3_deduplication"

    def __init__(self, filtering: FilteringService) -> None:
        self.filtering = filtering

    async def run(self, context: dict[str, Any], run: AgentRunHandle) -> dict[str, Any]:
        return await self.filtering.mark_duplicates()


class FilteringStage:
    name = "agent_4_rule_filtering"

    def __init__(self, filtering: FilteringService) -> None:
        self.filtering = filtering

    async def run(self, context: dict[str, Any], run: AgentRunHandle) -> dict[str, Any]:
        return await self.filtering.run()


class ScoringStage:
    name = "agent_5_job_scoring"

    def __init__(self, scoring: ScoringService) -> None:
        self.scoring = scoring

    async def run(self, context: dict[str, Any], run: AgentRunHandle) -> dict[str, Any]:
        return await self.scoring.run(run)


def summarize(result: PipelineResult) -> list[dict[str, Any]]:
    return [
        {
            "stage": s.name,
            "ok": s.ok,
            "agent_run_id": str(s.agent_run_id) if s.agent_run_id else None,
            "error": s.error,
        }
        for s in result.stages
    ]


class JobPipeline:
    def __init__(
        self,
        discovery: DiscoveryService,
        filtering: FilteringService,
        scoring: ScoringService,
        sessionmaker: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self.discovery = discovery
        self.filtering = filtering
        self.scoring = scoring
        self.sessionmaker = sessionmaker
        self._lock = asyncio.Lock()

    def _after_discovery(self) -> list[PipelineStage]:
        return [
            DeduplicationStage(self.filtering),
            FilteringStage(self.filtering),
            ScoringStage(self.scoring),
        ]

    async def execute(
        self,
        run_id: uuid.UUID,
        *,
        company_ids: list[uuid.UUID] | None = None,
        only_due: bool = False,
    ) -> dict[str, Any]:
        """Full pipeline for a discovery run row created by `discovery.start`."""
        context: dict[str, Any] = {
            "discovery_run_id": run_id,
            "company_ids": company_ids,
            "only_due": only_due,
        }
        stages = [DiscoveryStage(self.discovery), *self._after_discovery()]
        async with self._lock:
            result = await PipelineService(stages, self.sessionmaker).run(context)
        summary: dict[str, Any] = dict(context.get("discovery") or {"run_id": str(run_id)})
        summary["pipeline"] = summarize(result)
        summary["pipeline_ok"] = result.ok
        return summary

    async def run(
        self,
        trigger: str,
        *,
        company_ids: list[uuid.UUID] | None = None,
        only_due: bool = False,
    ) -> dict[str, Any]:
        """Start a discovery run (409 while one is running) and run everything."""
        run_id = await self.discovery.start(trigger)
        return await self.execute(run_id, company_ids=company_ids, only_due=only_due)

    async def rescore(self) -> dict[str, Any]:
        """Deduplicate, filter and score the stored jobs again (no crawling)."""
        async with self._lock:
            result = await PipelineService(self._after_discovery(), self.sessionmaker).run({})
        return {"pipeline": summarize(result), "pipeline_ok": result.ok}

    @property
    def busy(self) -> bool:
        return self._lock.locked()
