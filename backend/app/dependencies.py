"""FastAPI dependencies (dependency-injection wiring).

Routers declare what they need through the Annotated aliases below; tests
swap implementations with `app.dependency_overrides`.

Transaction rule: one request = one unit of work. Repositories only flush;
`get_db` commits when the handler returns and rolls back if it raises.
"""

from collections.abc import AsyncIterator
from typing import Annotated, cast

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.base import Connector
from app.core.config import Settings, get_settings
from app.core.database import session_scope
from app.core.security import Principal, get_current_user
from app.scheduler.background import BackgroundTaskManager
from app.scheduler.scheduler import SchedulerService
from app.services.automation_service import AutomationService
from app.services.company_service import CompanyService
from app.services.discovery_service import DiscoveryService
from app.services.job_service import JobService
from app.services.lifecycle_service import LifecycleService
from app.services.package_service import PackageGenerator, PackageWorkflow
from app.services.pipeline_service import JobPipeline
from app.services.profile_service import ProfileService
from app.services.resume_processing import ResumeProcessor
from app.services.resume_service import ResumeService
from app.services.scoring_service import ScoringService
from app.services.settings_service import SettingsService


async def get_db() -> AsyncIterator[AsyncSession]:
    async with session_scope() as session:
        yield session


def get_task_manager(request: Request) -> BackgroundTaskManager:
    return cast(BackgroundTaskManager, request.app.state.task_manager)


def get_scheduler(request: Request) -> SchedulerService:
    return cast(SchedulerService, request.app.state.scheduler)


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
    return cast(Settings, request.app.state.settings)


def get_processor(request: Request) -> ResumeProcessor:
    return cast(ResumeProcessor, request.app.state.processor)


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


# ------------------------------------------------------------ Phase 5 services
def get_connectors(request: Request) -> dict[str, Connector]:
    return cast(dict[str, Connector], request.app.state.connectors)


def get_discovery(request: Request) -> DiscoveryService:
    return cast(DiscoveryService, request.app.state.discovery)


ConnectorsDep = Annotated[dict[str, Connector], Depends(get_connectors)]
DiscoveryDep = Annotated[DiscoveryService, Depends(get_discovery)]


# ------------------------------------------------------------ Phase 6 services
def get_pipeline(request: Request) -> JobPipeline:
    return cast(JobPipeline, request.app.state.pipeline)


def get_scoring(request: Request) -> ScoringService:
    return cast(ScoringService, request.app.state.scoring)


PipelineDep = Annotated[JobPipeline, Depends(get_pipeline)]
ScoringDep = Annotated[ScoringService, Depends(get_scoring)]


# ------------------------------------------------------------ Phase 7 services
def get_package_generator(request: Request) -> PackageGenerator:
    return cast(PackageGenerator, request.app.state.packages)


def get_package_workflow(request: Request, db: DbSession) -> PackageWorkflow:
    return PackageWorkflow(db, request.app.state.storage)


def get_lifecycle(request: Request) -> LifecycleService:
    return cast(LifecycleService, request.app.state.lifecycle)


LifecycleDep = Annotated[LifecycleService, Depends(get_lifecycle)]
PackageGeneratorDep = Annotated[PackageGenerator, Depends(get_package_generator)]
PackageWorkflowDep = Annotated[PackageWorkflow, Depends(get_package_workflow)]


# ------------------------------------------------------------ Phase 8 services
def get_automation(request: Request) -> AutomationService:
    return cast(AutomationService, request.app.state.automation)


AutomationDep = Annotated[AutomationService, Depends(get_automation)]


def get_company_service(db: DbSession, connectors: ConnectorsDep) -> CompanyService:
    return CompanyService(db, connectors)


def get_job_service(db: DbSession) -> JobService:
    return JobService(db)


CompanyServiceDep = Annotated[CompanyService, Depends(get_company_service)]
JobServiceDep = Annotated[JobService, Depends(get_job_service)]
