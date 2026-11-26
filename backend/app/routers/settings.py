"""Settings router: the user's job-search preferences."""

from fastapi import APIRouter

from app.core.dependencies import SettingsServiceDep
from app.schemas.common import ERROR_RESPONSES
from app.schemas.settings import SettingsRead, SettingsUpdate

router = APIRouter(prefix="/settings", tags=["settings"], responses=ERROR_RESPONSES)


@router.get("", response_model=SettingsRead, summary="Get settings")
async def get_settings_endpoint(service: SettingsServiceDep) -> SettingsRead:
    return SettingsRead.model_validate(await service.get())


@router.patch("", response_model=SettingsRead, summary="Update settings (partial)")
async def update_settings(patch: SettingsUpdate, service: SettingsServiceDep) -> SettingsRead:
    return SettingsRead.model_validate(await service.update(patch))
