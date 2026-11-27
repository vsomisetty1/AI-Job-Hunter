"""Resumes router: upload, list, detail, versions, edits, download, delete."""

import logging
import uuid
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, File, Form, Response, UploadFile, status

from app.dependencies import (
    AppSettingsDep,
    DbSession,
    ProcessorDep,
    ProfileServiceDep,
    ResumeServiceDep,
    TaskManagerDep,
)
from app.models.resume import Resume
from app.schemas.candidate_profile import TaskAccepted
from app.schemas.common import ERROR_RESPONSES, ErrorResponse
from app.schemas.parsed_resume import ParsedResume
from app.schemas.resume import (
    ParsedResumeUpdate,
    ReparseRequest,
    ResumeDetail,
    ResumeRead,
    ResumeVersionRead,
    ResumeVersionSummary,
    TailoredVersionCreate,
    UploadResponse,
)
from app.services.resume_processing import PROFILE_TASK_KEY
from app.services.resume_service import ResumeService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/resumes", tags=["resumes"], responses=ERROR_RESPONSES)
NOT_FOUND: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorResponse, "description": "Resume or version not found"}
}


async def _detail(service: ResumeService, resume: Resume) -> ResumeDetail:
    parsed_version = await service.latest_parsed(resume.id)
    versions = await service.list_versions(resume.id)
    return ResumeDetail(
        **ResumeRead.model_validate(resume).model_dump(),
        parsed=ParsedResume.model_validate(parsed_version.content) if parsed_version else None,
        parsed_version_id=parsed_version.id if parsed_version else None,
        versions=[ResumeVersionSummary.model_validate(v) for v in versions],
    )


@router.post(
    "",
    response_model=UploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a resume (PDF or DOCX)",
    responses={
        409: {"model": ErrorResponse, "description": "Same file already uploaded"},
        413: {"model": ErrorResponse, "description": "File too large"},
        415: {"model": ErrorResponse, "description": "Not a PDF or DOCX"},
    },
)
async def upload_resume(
    service: ResumeServiceDep,
    profiles: ProfileServiceDep,
    db: DbSession,
    tasks: TaskManagerDep,
    processor: ProcessorDep,
    settings: AppSettingsDep,
    file: UploadFile = File(description="PDF or DOCX, up to MAX_UPLOAD_MB"),
    make_primary: bool = Form(default=False, description="Use this resume for the profile"),
) -> UploadResponse:
    data = await file.read(settings.max_upload_bytes + 1)
    result = await service.upload(data, file.filename, make_primary=make_primary)
    resume = result.resume
    if resume.is_primary:
        await profiles.mark("pending")
    try:
        await db.commit()  # the background task reads these rows
    except BaseException:
        await service.delete_file(resume.storage_path)
        raise
    detail = await _detail(service, resume)  # before the task starts writing new versions
    resume_id = resume.id
    task = tasks.submit(
        "resume-processing",
        lambda: processor.enrich_and_profile(resume_id),
        dedupe_key=f"resume:{resume_id}",
    )
    return UploadResponse(resume=detail, task_id=task.id)


@router.get("", response_model=list[ResumeRead], summary="List resumes")
async def list_resumes(service: ResumeServiceDep) -> list[ResumeRead]:
    return [ResumeRead.model_validate(r) for r in await service.list_resumes()]


@router.get("/{resume_id}", response_model=ResumeDetail, summary="Resume with parsed data",
            responses=NOT_FOUND)  # fmt: skip
async def get_resume(resume_id: uuid.UUID, service: ResumeServiceDep) -> ResumeDetail:
    return await _detail(service, await service.get(resume_id))


@router.delete(
    "/{resume_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a resume",
    responses=NOT_FOUND,
)  # fmt: skip
async def delete_resume(
    resume_id: uuid.UUID,
    service: ResumeServiceDep,
    profiles: ProfileServiceDep,
    db: DbSession,
    tasks: TaskManagerDep,
    processor: ProcessorDep,
) -> Response:
    path, promoted = await service.delete(resume_id)
    if promoted is not None:
        await profiles.mark("pending")
    await db.commit()
    await service.delete_file(path)  # after commit: never delete a file still referenced
    if promoted is not None:  # the profile was built from the deleted resume
        tasks.submit(
            "profile-generation",
            lambda: processor.generate_profile(resume_id=promoted),
            dedupe_key=PROFILE_TASK_KEY,
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{resume_id}/primary", response_model=TaskAccepted, status_code=status.HTTP_202_ACCEPTED,
    summary="Make this the primary resume and rebuild the profile from it", responses=NOT_FOUND,
)  # fmt: skip
async def make_primary(
    resume_id: uuid.UUID,
    service: ResumeServiceDep,
    profiles: ProfileServiceDep,
    db: DbSession,
    tasks: TaskManagerDep,
    processor: ProcessorDep,
) -> TaskAccepted:
    await service.set_primary(resume_id)
    await profiles.mark("pending")
    await db.commit()
    task = tasks.submit(
        "profile-generation",
        lambda: processor.generate_profile(resume_id=resume_id),
        dedupe_key=PROFILE_TASK_KEY,
    )
    return TaskAccepted(task_id=task.id, status=task.status, detail="Profile is being rebuilt.")


@router.get("/{resume_id}/download", summary="Download the original file", responses=NOT_FOUND)
async def download_resume(resume_id: uuid.UUID, service: ResumeServiceDep) -> Response:
    data, filename, content_type = await service.download(resume_id)
    ascii_name = filename.encode("ascii", "ignore").decode().replace('"', "") or "resume"
    return Response(
        content=data,
        media_type=content_type,
        headers={
            # Always a download, never rendered inline by the browser.
            "Content-Disposition": (
                f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"
            ),
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; sandbox",
            "Cache-Control": "no-store",
        },
    )


@router.get("/{resume_id}/versions", response_model=list[ResumeVersionSummary],
            summary="Version history (newest first)", responses=NOT_FOUND)  # fmt: skip
async def list_versions(
    resume_id: uuid.UUID, service: ResumeServiceDep
) -> list[ResumeVersionSummary]:
    return [ResumeVersionSummary.model_validate(v) for v in await service.list_versions(resume_id)]


@router.get("/{resume_id}/versions/{version_id}", response_model=ResumeVersionRead,
            summary="One version with its content", responses=NOT_FOUND)  # fmt: skip
async def get_version(
    resume_id: uuid.UUID, version_id: uuid.UUID, service: ResumeServiceDep
) -> ResumeVersionRead:
    return ResumeVersionRead.model_validate(await service.get_version(resume_id, version_id))


@router.put(
    "/{resume_id}/parsed", response_model=ResumeVersionRead, status_code=status.HTTP_201_CREATED,
    summary="Save edited parsed data as a new version", responses=NOT_FOUND,
)  # fmt: skip
async def update_parsed(
    resume_id: uuid.UUID, body: ParsedResumeUpdate, service: ResumeServiceDep
) -> ResumeVersionRead:
    version = await service.update_parsed(resume_id, body.data, body.change_summary)
    return ResumeVersionRead.model_validate(version)


@router.post(
    "/{resume_id}/reparse", response_model=TaskAccepted, status_code=status.HTTP_202_ACCEPTED,
    summary="Parse the original file again (new version)", responses=NOT_FOUND,
)  # fmt: skip
async def reparse(
    resume_id: uuid.UUID,
    body: ReparseRequest,
    service: ResumeServiceDep,
    tasks: TaskManagerDep,
    processor: ProcessorDep,
) -> TaskAccepted:
    await service.get(resume_id)
    task = tasks.submit(
        "resume-reparse",
        lambda: processor.reparse(resume_id, use_llm=body.use_llm),
        dedupe_key=f"resume:{resume_id}",
    )
    return TaskAccepted(task_id=task.id, status=task.status, detail="Re-parsing started.")


@router.post(
    "/{resume_id}/versions/tailored", response_model=ResumeVersionRead,
    status_code=status.HTTP_201_CREATED, summary="Store a tailored version",
    responses=NOT_FOUND,
)  # fmt: skip
async def create_tailored(
    resume_id: uuid.UUID, body: TailoredVersionCreate, service: ResumeServiceDep
) -> ResumeVersionRead:
    return ResumeVersionRead.model_validate(await service.create_tailored(resume_id, body))
