"""Scheduler framework (APScheduler, in-process).

`SchedulerService` owns an AsyncIOScheduler started and stopped by the app
lifespan. Jobs are registered in `app.scheduler.tasks`. Every job runs with
`max_instances=1` and `coalesce=True`: a slow run is never doubled up, and
missed runs (e.g. laptop asleep) collapse into one.

Single process only: run the backend with one uvicorn worker, otherwise
each worker would run every job.
"""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.core.exceptions import NotFoundError, ServiceUnavailableError

logger = logging.getLogger(__name__)

JobFn = Callable[[], Awaitable[Any]]


@dataclass(frozen=True)
class JobInfo:
    id: str
    name: str
    trigger: str
    next_run_at: datetime | None


class SchedulerService:
    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled
        self._scheduler = AsyncIOScheduler(
            timezone=UTC,
            job_defaults={"max_instances": 1, "coalesce": True, "misfire_grace_time": 300},
        )

    @property
    def running(self) -> bool:
        return self._scheduler.running

    def add_interval_job(
        self,
        job_id: str,
        fn: JobFn,
        *,
        minutes: int,
        name: str | None = None,
        run_immediately: bool = False,
    ) -> None:
        kwargs: dict[str, Any] = {}
        if run_immediately:
            kwargs["next_run_time"] = datetime.now(UTC)
        # Note: passing next_run_time=None would add the job paused, so the
        # key is only set when needed.
        self._scheduler.add_job(
            fn,
            IntervalTrigger(minutes=minutes, timezone=UTC),
            id=job_id,
            name=name or job_id,
            replace_existing=True,
            **kwargs,
        )

    def start(self) -> None:
        if not self.enabled:
            logger.info("scheduler disabled (SCHEDULER_ENABLED=false)")
            return
        if not self._scheduler.running:
            self._scheduler.start()
            logger.info("scheduler started with %d job(s)", len(self._scheduler.get_jobs()))

    def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            logger.info("scheduler stopped")

    def list_jobs(self) -> list[JobInfo]:
        return [
            JobInfo(j.id, j.name, str(j.trigger), getattr(j, "next_run_time", None))
            for j in self._scheduler.get_jobs()
        ]

    def run_now(self, job_id: str) -> JobInfo:
        """Pull a job's next run forward to now (keeps max_instances=1 protection)."""
        job = self._scheduler.get_job(job_id)
        if job is None:
            raise NotFoundError("Scheduled job not found", {"job_id": job_id})
        if not self._scheduler.running:
            raise ServiceUnavailableError("Scheduler is not running", {"job_id": job_id})
        job = job.modify(next_run_time=datetime.now(UTC))
        return JobInfo(job.id, job.name, str(job.trigger), job.next_run_time)
