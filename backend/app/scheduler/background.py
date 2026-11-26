"""In-process background task framework.

`BackgroundTaskManager` runs async work outside the request/response cycle
(e.g. "parse this resume", "run discovery now"), with:

* bounded concurrency (a semaphore),
* de-duplication by key (a second submit returns the task already running),
* status tracking for the API (`queued` -> `running` -> `succeeded`/`failed`/`cancelled`),
* clean cancellation on shutdown.

Work functions receive no arguments; close over what they need and open
their own database session with `app.core.database.session_scope()` (the
request session is closed by the time they run).

Single-process by design (personal use, one uvicorn worker). Durable,
multi-worker queues are out of scope.
"""

import asyncio
import logging
import uuid
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from app.core.logging import request_id_var

logger = logging.getLogger(__name__)

TaskStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]
TaskFn = Callable[[], Awaitable[Any]]


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass
class TaskInfo:
    id: str
    name: str
    dedupe_key: str | None
    status: TaskStatus = "queued"
    created_at: datetime = field(default_factory=_now)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None
    result: Any = None

    @property
    def done(self) -> bool:
        return self.status in ("succeeded", "failed", "cancelled")


class BackgroundTaskManager:
    def __init__(self, max_concurrency: int = 4, history_size: int = 200) -> None:
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._history_size = history_size
        self._infos: OrderedDict[str, TaskInfo] = OrderedDict()
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._active_keys: dict[str, str] = {}
        self._closed = False

    def submit(self, name: str, fn: TaskFn, *, dedupe_key: str | None = None) -> TaskInfo:
        if self._closed:
            raise RuntimeError("task manager is shut down")
        if dedupe_key and (existing := self._active_keys.get(dedupe_key)):
            return self._infos[existing]

        info = TaskInfo(id=uuid.uuid4().hex, name=name, dedupe_key=dedupe_key)
        self._infos[info.id] = info
        if dedupe_key:
            self._active_keys[dedupe_key] = info.id
        self._tasks[info.id] = asyncio.create_task(self._run(info, fn), name=f"bg:{name}")
        self._trim_history()
        return info

    async def _run(self, info: TaskInfo, fn: TaskFn) -> None:
        token = request_id_var.set(f"task-{info.id[:12]}")
        try:
            async with self._semaphore:
                info.status, info.started_at = "running", _now()
                logger.info("task started: %s", info.name, extra={"task_id": info.id})
                info.result = await fn()
                info.status = "succeeded"
        except asyncio.CancelledError:
            info.status = "cancelled"
            raise
        except Exception as exc:
            info.status, info.error = "failed", f"{type(exc).__name__}: {exc}"
            logger.exception("task failed: %s", info.name, extra={"task_id": info.id})
        finally:
            info.finished_at = _now()
            self._tasks.pop(info.id, None)
            if info.dedupe_key and self._active_keys.get(info.dedupe_key) == info.id:
                del self._active_keys[info.dedupe_key]
            request_id_var.reset(token)

    def get(self, task_id: str) -> TaskInfo | None:
        return self._infos.get(task_id)

    def list(self) -> list[TaskInfo]:
        return list(reversed(self._infos.values()))

    async def wait(self, task_id: str, timeout: float | None = None) -> TaskInfo:
        task = self._tasks.get(task_id)
        if task is not None:
            await asyncio.wait({task}, timeout=timeout)
        return self._infos[task_id]

    def cancel(self, task_id: str) -> bool:
        task = self._tasks.get(task_id)
        return bool(task and task.cancel())

    async def shutdown(self, timeout: float = 10.0) -> None:
        self._closed = True
        tasks = list(self._tasks.values())
        if not tasks:
            return
        _, pending = await asyncio.wait(tasks, timeout=timeout)
        for t in pending:
            t.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
            logger.warning("cancelled %d background task(s) on shutdown", len(pending))

    def _trim_history(self) -> None:
        excess = len(self._infos) - self._history_size
        for task_id in [tid for tid, i in self._infos.items() if i.done][: max(excess, 0)]:
            del self._infos[task_id]
