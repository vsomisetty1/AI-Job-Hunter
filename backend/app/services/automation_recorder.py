"""Agent 10's recorder for the automation pipeline: logs, checkpoints,
screenshots and browser cookies, each in its own short transaction."""

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.automation.checkpoints import Checkpoint
from app.models.application_submission import (
    ApplicationSubmission,
)
from app.repositories.automation_repository import (
    BrowserSessionRepository,
    SubmissionRepository,
)
from app.storage import StorageBackend

logger = logging.getLogger(__name__)

logger = logging.getLogger(__name__)

SCREENSHOT_PREFIX = "automation"
MAX_SCREENSHOTS = 30


def _now() -> datetime:
    return datetime.now(UTC)


class DbRecorder:
    """Agent 10's recorder: each call is its own short transaction, so the
    review screen shows progress while a run is still going."""

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        storage: StorageBackend,
        submission_id: uuid.UUID,
    ) -> None:
        self.sessionmaker = sessionmaker
        self.storage = storage
        self.submission_id = submission_id

    async def log(self, level: str, step: str, message: str, **detail: Any) -> None:
        logger.log(
            {"debug": logging.DEBUG, "warning": logging.WARNING, "error": logging.ERROR}.get(
                level, logging.INFO
            ),
            "automation %s: %s",
            step,
            message,
            extra={"submission_id": str(self.submission_id)},
        )
        async with self.sessionmaker() as session, session.begin():
            await SubmissionRepository(session).add_log(
                self.submission_id, level, step, message, _jsonable(detail)
            )

    async def checkpoint(self, step: str, checkpoint: Checkpoint) -> None:
        async with self.sessionmaker() as session, session.begin():
            sub = await session.get(ApplicationSubmission, self.submission_id)
            if sub is not None:
                sub.step, sub.checkpoint = step, checkpoint.as_json()

    async def screenshot(self, step: str, label: str, png: bytes) -> None:
        async with self.sessionmaker() as session, session.begin():
            sub = await session.get(ApplicationSubmission, self.submission_id, with_for_update=True)
            if sub is None:
                return
            n = len(sub.screenshots) + 1
            if n > MAX_SCREENSHOTS:
                return
            path = f"{SCREENSHOT_PREFIX}/{self.submission_id}/{n:02d}-{step}.png"
            await self.storage.put(path, png, "image/png")
            sub.screenshots = [
                *sub.screenshots,
                {"path": path, "step": step, "label": label, "at": _now().isoformat()},
            ]

    async def save_browser_state(self, platform: str, state: dict[str, Any]) -> None:
        if not state:
            return
        async with self.sessionmaker() as session, session.begin():
            await BrowserSessionRepository(session).save(platform, state, _now())


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(v) for v in value]
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    return str(value)
