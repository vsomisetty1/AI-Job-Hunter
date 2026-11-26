"""FastAPI dependencies (dependency-injection wiring).

Routers declare what they need through the Annotated aliases below; tests
swap implementations with `app.dependency_overrides`.

Transaction rule: one request = one unit of work. Repositories only flush;
`get_db` commits when the handler returns and rolls back if it raises.
"""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.database import get_sessionmaker
from app.core.security import Principal, get_current_user
from app.scheduler.background import BackgroundTaskManager
from app.scheduler.scheduler import SchedulerService
from app.services.settings_service import SettingsService


async def get_db() -> AsyncIterator[AsyncSession]:
    async with get_sessionmaker()() as session:
        try:
            yield session
            await session.commit()
        except BaseException:
            await session.rollback()
            raise


def get_task_manager(request: Request) -> BackgroundTaskManager:
    return request.app.state.task_manager


def get_scheduler(request: Request) -> SchedulerService:
    return request.app.state.scheduler


SettingsDep = Annotated[Settings, Depends(get_settings)]
DbSession = Annotated[AsyncSession, Depends(get_db)]
CurrentUser = Annotated[Principal, Depends(get_current_user)]
TaskManagerDep = Annotated[BackgroundTaskManager, Depends(get_task_manager)]
SchedulerDep = Annotated[SchedulerService, Depends(get_scheduler)]


def get_settings_service(db: DbSession) -> SettingsService:
    return SettingsService(db)


SettingsServiceDep = Annotated[SettingsService, Depends(get_settings_service)]
