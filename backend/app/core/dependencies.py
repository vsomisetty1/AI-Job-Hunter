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
from app.services.profile_service import ProfileService
from app.services.resume_processing import ResumeProcessor
from app.services.resume_service import ResumeService
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


# ------------------------------------------------------------ Phase 4 services
def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_processor(request: Request) -> ResumeProcessor:
    return request.app.state.processor


def get_resume_service(request: Request, db: DbSession) -> ResumeService:
    state = request.app.state
    return ResumeService(
        db,
        settings=state.settings,
        storage=state.storage,
        scanner=state.scanner,
        parser=state.parser_agent,
    )


def get_profile_service(db: DbSession) -> ProfileService:
    return ProfileService(db)


AppSettingsDep = Annotated[Settings, Depends(get_app_settings)]
ProcessorDep = Annotated[ResumeProcessor, Depends(get_processor)]
ResumeServiceDep = Annotated[ResumeService, Depends(get_resume_service)]
ProfileServiceDep = Annotated[ProfileService, Depends(get_profile_service)]
