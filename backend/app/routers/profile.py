"""Candidate profile router."""

from typing import Any

from fastapi import APIRouter, status

from app.dependencies import DbSession, ProcessorDep, ProfileServiceDep, TaskManagerDep
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
    body: CandidateProfileUpdate, service: ProfileServiceDep
) -> CandidateProfileRead:
    return to_read(await service.update(body))


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
