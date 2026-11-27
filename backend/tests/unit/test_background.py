import asyncio

import pytest

from app.scheduler.background import BackgroundTaskManager


async def test_task_succeeds_and_records_result():
    mgr = BackgroundTaskManager()

    async def work():
        return 42

    info = mgr.submit("answer", work)
    info = await mgr.wait(info.id, timeout=1)
    assert info.status == "succeeded" and info.result == 42
    assert info.started_at and info.finished_at


async def test_failure_is_recorded_not_raised():
    mgr = BackgroundTaskManager()

    async def boom():
        raise ValueError("nope")

    info = await mgr.wait(mgr.submit("boom", boom).id, timeout=1)
    assert info.status == "failed"
    assert info.error == "ValueError: nope"


async def test_dedupe_key_returns_running_task():
    mgr = BackgroundTaskManager()
    gate = asyncio.Event()

    async def slow():
        await gate.wait()

    first = mgr.submit("slow", slow, dedupe_key="k")
    second = mgr.submit("slow", slow, dedupe_key="k")
    assert first.id == second.id
    gate.set()
    await mgr.wait(first.id, timeout=1)
    third = mgr.submit("slow", slow, dedupe_key="k")  # key released after completion
    assert third.id != first.id
    await mgr.wait(third.id, timeout=1)


async def test_concurrency_limit():
    mgr = BackgroundTaskManager(max_concurrency=2)
    running = 0
    peak = 0

    async def work():
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.01)
        running -= 1

    infos = [mgr.submit(f"t{i}", work) for i in range(6)]
    for i in infos:
        await mgr.wait(i.id, timeout=1)
    assert peak == 2


async def test_shutdown_cancels_pending_and_rejects_new():
    mgr = BackgroundTaskManager()

    async def forever():
        await asyncio.sleep(3600)

    info = mgr.submit("forever", forever)
    await asyncio.sleep(0)
    await mgr.shutdown(timeout=0.05)
    assert mgr.get(info.id).status == "cancelled"
    with pytest.raises(RuntimeError):
        mgr.submit("late", forever)


async def test_history_is_bounded():
    mgr = BackgroundTaskManager(history_size=3)

    async def noop():
        return None

    for i in range(6):
        await mgr.wait(mgr.submit(f"t{i}", noop).id, timeout=1)
    mgr.submit("last", noop)
    assert len(mgr.list_tasks()) <= 4
