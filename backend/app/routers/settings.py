"""Settings router: the user's job-search preferences."""

from fastapi import APIRouter

from app.dependencies import (
    AppSettingsDep,
    DbSession,
    PipelineDep,
    SettingsServiceDep,
    TaskManagerDep,
)
from app.routers.scoring import start_rescore
from app.schemas.common import ERROR_RESPONSES
from app.schemas.settings import SCORING_FIELDS, SettingsRead, SettingsUpdate

router = APIRouter(prefix="/settings", tags=["settings"], responses=ERROR_RESPONSES)


@router.get("", response_model=SettingsRead, summary="Get settings")
async def get_settings_endpoint(service: SettingsServiceDep) -> SettingsRead:
    return SettingsRead.model_validate(await service.get())


@router.patch(
    "",
    response_model=SettingsRead,
    summary="Update settings (partial); filter and scoring changes re-score the jobs",
)
async def update_settings(
    patch: SettingsUpdate,
    service: SettingsServiceDep,
    db: DbSession,
    tasks: TaskManagerDep,
    pipeline: PipelineDep,
    config: AppSettingsDep,
) -> SettingsRead:
    updated = SettingsRead.model_validate(await service.update(patch))
    if config.rescore_on_change and patch.changes().keys() & SCORING_FIELDS:
        await db.commit()  # the background run must see the new settings
        start_rescore(tasks, pipeline)
    return updated
