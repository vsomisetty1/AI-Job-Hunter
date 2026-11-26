"""Scheduled background tasks.

Each job opens its own unit of work and checks the user's settings at run
time, so toggling `discovery_enabled` takes effect without a restart.
"""

import logging

from app.core.config import Settings
from app.core.database import session_scope
from app.repositories.settings_repository import SettingsRepository
from app.scheduler.scheduler import SchedulerService
from app.services.pipeline_service import PipelineService

logger = logging.getLogger(__name__)

DISCOVERY_JOB_ID = "job_discovery"


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
