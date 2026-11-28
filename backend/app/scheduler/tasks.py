"""Scheduled background tasks.

Each job opens its own unit of work and checks the user's settings at run
time, so toggling `discovery_enabled` takes effect without a restart.
"""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, update

from app.core.config import Settings
from app.core.database import session_scope
from app.learning.service import LearningService
from app.models.agent_run import AgentRun
from app.models.candidate_profile import CandidateProfile
from app.models.discovery_run import DiscoveryRun
from app.models.llm_cache_entry import LLMCacheEntry
from app.repositories.package_repository import PackageRepository
from app.repositories.settings_repository import SettingsRepository
from app.scheduler.scheduler import SchedulerService
from app.services.automation_service import AutomationService
from app.services.discovery_service import DiscoveryInProgressError
from app.services.lifecycle_service import LifecycleService
from app.services.pipeline_service import JobPipeline

logger = logging.getLogger(__name__)

DISCOVERY_JOB_ID = "job_discovery"
MAINTENANCE_JOB_ID = "maintenance"
AUTOMATION_SWEEP_JOB_ID = "automation_idle_sweep"
LEARNING_JOB_ID = "learning"
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
        discovery = await session.execute(
            update(DiscoveryRun)
            .where(DiscoveryRun.status == "running")
            .values(status="cancelled", error=INTERRUPTED, finished_at=func.clock_timestamp())
        )
        packages = await PackageRepository(session).mark_interrupted(INTERRUPTED)
    result = {
        "packages": packages,
        "profiles": profiles.rowcount,  # type: ignore[attr-defined]
        "agent_runs": runs.rowcount,  # type: ignore[attr-defined]
        "discovery_runs": discovery.rowcount,  # type: ignore[attr-defined]
    }
    if any(result.values()):
        logger.warning("recovered interrupted work", extra=result)
    return result


async def run_maintenance(settings: Settings) -> dict[str, int]:
    """Prune expired Claude cache entries, old agent_runs and old discovery_runs."""
    now = datetime.now(UTC)
    cutoff = now - timedelta(days=settings.agent_run_retention_days)
    async with session_scope() as session:
        cache = await session.execute(delete(LLMCacheEntry).where(LLMCacheEntry.expires_at < now))
        runs = await session.execute(
            delete(AgentRun).where(AgentRun.started_at < cutoff, AgentRun.status != "running")
        )
        discovery = await session.execute(
            delete(DiscoveryRun).where(
                DiscoveryRun.started_at < cutoff, DiscoveryRun.status != "running"
            )
        )
    result = {
        "llm_cache_entries": cache.rowcount,  # type: ignore[attr-defined]
        "agent_runs": runs.rowcount,  # type: ignore[attr-defined]
        "discovery_runs": discovery.rowcount,  # type: ignore[attr-defined]
    }
    logger.info("maintenance finished", extra=result)
    return result


async def run_discovery_cycle(pipeline: JobPipeline) -> dict[str, object]:
    """Scheduled, incremental refresh: only companies whose last crawl is due, then
    deduplication, filtering and scoring of what was found."""
    async with session_scope() as session:
        settings = await SettingsRepository(session).get_singleton()
        enabled = settings.discovery_enabled
    if not enabled:
        logger.info("discovery skipped: disabled in settings")
        return {"skipped": True, "reason": "discovery_disabled"}
    try:
        summary = await pipeline.run("scheduled", only_due=True)
    except DiscoveryInProgressError:
        logger.info("discovery skipped: a run is already in progress")
        return {"skipped": True, "reason": "in_progress"}
    return {"skipped": False} | {k: v for k, v in summary.items() if k != "details"}


def register_jobs(
    scheduler: SchedulerService,
    settings: Settings,
    pipeline: JobPipeline,
    lifecycle: LifecycleService | None = None,
    automation: AutomationService | None = None,
    learning: LearningService | None = None,
) -> None:
    async def discover() -> dict[str, object]:
        return await run_discovery_cycle(pipeline)

    scheduler.add_interval_job(
        DISCOVERY_JOB_ID,
        discover,
        minutes=settings.discovery_interval_minutes,
        name="Discover, deduplicate, filter and score jobs",
    )

    async def maintenance() -> dict[str, object]:
        result: dict[str, object] = dict(await run_maintenance(settings))
        if lifecycle is not None:
            try:
                result["storage"] = await lifecycle.run()
            except Exception:  # storage unreachable: the next run retries
                logger.exception("storage cleanup failed")
        if automation is not None:
            result["automation_logs"] = await automation.prune_logs()
        return result

    scheduler.add_interval_job(
        MAINTENANCE_JOB_ID,
        maintenance,
        minutes=24 * 60,
        name="Prune caches, old run logs, old packages and orphaned files",
    )

    if automation is not None:

        async def sweep() -> dict[str, object]:
            return {"closed": await automation.sweep_idle()}

        scheduler.add_interval_job(
            AUTOMATION_SWEEP_JOB_ID,
            sweep,
            minutes=5,
            name="Close application forms left open past the idle timeout",
        )

    if learning is not None:

        async def learn() -> dict[str, object]:
            return dict(await learning.refresh("scheduled"))

        scheduler.add_interval_job(
            LEARNING_JOB_ID,
            learn,
            minutes=24 * 60,
            name="Learning Agent: analyse outcomes, update insights and recommendations",
        )
