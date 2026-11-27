"""System router: app info, scheduled jobs, background tasks."""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, status
from pydantic import BaseModel

from app.core.exceptions import NotFoundError
from app.dependencies import CurrentUser, LifecycleDep, SchedulerDep, SettingsDep, TaskManagerDep
from app.scheduler.background import TaskStatus
from app.schemas.common import ERROR_RESPONSES, ErrorResponse

router = APIRouter(prefix="/system", tags=["system"], responses=ERROR_RESPONSES)


class SystemInfo(BaseModel):
    name: str
    version: str
    environment: str
    auth_mode: str
    user: str
    scheduler_running: bool


class ScheduledJob(BaseModel):
    id: str
    name: str
    trigger: str
    next_run_at: datetime | None


class BackgroundTask(BaseModel):
    id: str
    name: str
    status: TaskStatus
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    error: str | None
    result: Any = None


@router.get("/info", response_model=SystemInfo, summary="App and auth info")
async def info(settings: SettingsDep, user: CurrentUser, scheduler: SchedulerDep) -> SystemInfo:
    return SystemInfo(
        name=settings.app_name,
        version=settings.app_version,
        environment=settings.app_env,
        auth_mode=settings.auth_mode,
        user=user.name,
        scheduler_running=scheduler.running,
    )


@router.get("/jobs", response_model=list[ScheduledJob], summary="List scheduled jobs")
async def list_jobs(scheduler: SchedulerDep) -> list[ScheduledJob]:
    return [ScheduledJob(**vars(j)) for j in scheduler.list_jobs()]


@router.post(
    "/jobs/{job_id}/run",
    response_model=ScheduledJob,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Run a scheduled job now",
    responses={404: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
)
async def run_job(job_id: str, scheduler: SchedulerDep) -> ScheduledJob:
    return ScheduledJob(**vars(scheduler.run_now(job_id)))


@router.get("/tasks", response_model=list[BackgroundTask], summary="List background tasks")
async def list_tasks(tasks: TaskManagerDep) -> list[BackgroundTask]:
    return [BackgroundTask.model_validate(t, from_attributes=True) for t in tasks.list_tasks()]


@router.get(
    "/tasks/{task_id}",
    response_model=BackgroundTask,
    summary="Get a background task",
    responses={404: {"model": ErrorResponse}},
)
async def get_task(task_id: str, tasks: TaskManagerDep) -> BackgroundTask:
    info = tasks.get(task_id)
    if info is None:
        raise NotFoundError("Background task not found", {"task_id": task_id})
    return BackgroundTask.model_validate(info, from_attributes=True)


@router.get("/storage", summary="Storage use, orphaned files and retention policy")
async def storage_report(lifecycle: LifecycleDep) -> dict[str, Any]:
    return await lifecycle.report()


@router.post("/storage/cleanup", summary="Prune old packages and orphaned files now")
async def storage_cleanup(lifecycle: LifecycleDep) -> dict[str, Any]:
    return await lifecycle.run()
