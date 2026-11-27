"""Candidate profile router."""

from typing import Any

from fastapi import APIRouter, status

from app.dependencies import (
    AppSettingsDep,
    DbSession,
    PipelineDep,
    ProcessorDep,
    ProfileServiceDep,
    TaskManagerDep,
)
from app.routers.scoring import start_rescore
from app.schemas.candidate_profile import (
    CandidateProfileRead,
    CandidateProfileUpdate,
    RegenerateProfileRequest,
    TaskAccepted,
)
from app.schemas.common import ERROR_RESPONSES, ErrorResponse
from app.services.profile_service import to_read
from app.services.resume_processing import PROFILE_TASK_KEY

router = APIRouter(prefix="/profile", tags=["profile"], responses=ERROR_RESPONSES)
NO_PROFILE: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorResponse, "description": "No profile yet"}
}


@router.get(
    "", response_model=CandidateProfileRead, summary="Get the profile", responses=NO_PROFILE
)
async def get_profile(service: ProfileServiceDep) -> CandidateProfileRead:
    return to_read(await service.get())


@router.patch(
    "", response_model=CandidateProfileRead, summary="Edit the profile", responses=NO_PROFILE
)
async def update_profile(
    body: CandidateProfileUpdate,
    service: ProfileServiceDep,
    db: DbSession,
    tasks: TaskManagerDep,
    pipeline: PipelineDep,
    config: AppSettingsDep,
) -> CandidateProfileRead:
    updated = to_read(await service.update(body))
    if config.rescore_on_change and body.changes():
        await db.commit()  # the background run must see the edited profile
        start_rescore(tasks, pipeline)  # skills, roles and level feed every score
    return updated


@router.post(
    "/regenerate",
    response_model=TaskAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Rebuild the profile from a resume",
    responses=NO_PROFILE,
)
async def regenerate_profile(
    body: RegenerateProfileRequest,
    service: ProfileServiceDep,
    db: DbSession,
    tasks: TaskManagerDep,
    processor: ProcessorDep,
) -> TaskAccepted:
    await service.get()
    await service.mark("pending")
    await db.commit()
    task = tasks.submit(
        "profile-generation",
        lambda: processor.generate_profile(
            resume_id=body.resume_id, keep_overrides=body.keep_overrides, use_llm=body.use_llm
        ),
        dedupe_key=PROFILE_TASK_KEY,
    )
    return TaskAccepted(task_id=task.id, status=task.status, detail="Profile generation started.")
