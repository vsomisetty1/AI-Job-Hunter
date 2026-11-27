import asyncio

import pytest

from app.core.exceptions import NotFoundError, ServiceUnavailableError
from app.scheduler.scheduler import SchedulerService


async def test_interval_job_is_scheduled_not_paused():
    sched = SchedulerService()

    async def job():
        return None

    sched.add_interval_job("j", job, minutes=60)
    sched.start()
    try:
        [info] = sched.list_jobs()
        assert info.id == "j" and info.next_run_at is not None
    finally:
        sched.shutdown()


async def test_run_now_executes_job():
    sched = SchedulerService()
    ran = asyncio.Event()

    async def job():
        ran.set()

    sched.add_interval_job("j", job, minutes=60)
    sched.start()
    try:
        sched.run_now("j")
        await asyncio.wait_for(ran.wait(), timeout=5)
    finally:
        sched.shutdown()


async def test_run_now_errors():
    sched = SchedulerService(enabled=False)

    async def job():
        return None

    sched.add_interval_job("j", job, minutes=60)
    sched.start()  # disabled: does not start
    assert not sched.running
    with pytest.raises(NotFoundError):
        sched.run_now("missing")
    with pytest.raises(ServiceUnavailableError):
        sched.run_now("j")
