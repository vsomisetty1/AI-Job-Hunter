"""Scheduled background tasks.

Each job opens its own unit of work and checks the user's settings at run
time, so toggling `discovery_enabled` takes effect without a restart.
"""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, update

from app.core.config import Settings
from app.core.database import session_scope
from app.models.agent_run import AgentRun
from app.models.candidate_profile import CandidateProfile
from app.models.llm_cache_entry import LLMCacheEntry
from app.repositories.settings_repository import SettingsRepository
from app.scheduler.scheduler import SchedulerService
from app.services.pipeline_service import PipelineService

logger = logging.getLogger(__name__)

DISCOVERY_JOB_ID = "job_discovery"
MAINTENANCE_JOB_ID = "maintenance"
INTERRUPTED = "Interrupted by a restart; run it again."


async def recover_interrupted_work() -> dict[str, int]:
    """At startup nothing can still be running (single process): close out work
    that a previous process left half-done, so the UI does not wait forever."""
    async with session_scope() as session:
        profiles = await session.execute(
            update(CandidateProfile)
            .where(CandidateProfile.inference_status.in_(("pending", "running")))
            .values(inference_status="failed", inference_error=INTERRUPTED)
        )
        runs = await session.execute(
            update(AgentRun)
            .where(AgentRun.status == "running")
            .values(status="cancelled", error=INTERRUPTED, finished_at=func.clock_timestamp())
        )
    result = {"profiles": profiles.rowcount, "agent_runs": runs.rowcount}  # type: ignore[attr-defined]
    if any(result.values()):
        logger.warning("recovered interrupted work", extra=result)
    return result


async def run_maintenance(settings: Settings) -> dict[str, int]:
    """Prune expired Claude cache entries and old agent_runs."""
    now = datetime.now(UTC)
    cutoff = now - timedelta(days=settings.agent_run_retention_days)
    async with session_scope() as session:
        cache = await session.execute(delete(LLMCacheEntry).where(LLMCacheEntry.expires_at < now))
        runs = await session.execute(
            delete(AgentRun).where(AgentRun.started_at < cutoff, AgentRun.status != "running")
        )
    result = {"llm_cache_entries": cache.rowcount, "agent_runs": runs.rowcount}  # type: ignore[attr-defined]
    logger.info("maintenance finished", extra=result)
    return result


async def run_discovery_cycle() -> dict[str, object]:
    async with session_scope() as session:
        settings = await SettingsRepository(session).get_singleton()
        enabled = settings.discovery_enabled
    if not enabled:
        logger.info("discovery skipped: disabled in settings")
        return {"skipped": True, "reason": "discovery_disabled"}
    result = await PipelineService.discovery().run({})
    logger.info("discovery cycle finished", extra={"stages": len(result.stages)})
    return {"skipped": False, "stages": [s.name for s in result.stages], "ok": result.ok}


def register_jobs(scheduler: SchedulerService, settings: Settings) -> None:
    scheduler.add_interval_job(
        DISCOVERY_JOB_ID,
        run_discovery_cycle,
        minutes=settings.discovery_interval_minutes,
        name="Discover, filter and score new jobs",
    )

    async def maintenance() -> dict[str, int]:
        return await run_maintenance(settings)

    scheduler.add_interval_job(
        MAINTENANCE_JOB_ID, maintenance, minutes=24 * 60, name="Prune caches and old run logs"
    )
