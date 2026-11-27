"""Packages router: generate, view, review, approve, reject, regenerate.

Generation runs in the background (202 + package id); poll GET /packages/{id}
until its status leaves 'generating'. Nothing here submits an application:
'submitted' only records that you applied yourself.
"""

import uuid
from typing import Annotated, Any, Literal
from urllib.parse import quote

from fastapi import APIRouter, Query, Response, status

from app.dependencies import DbSession, PackageGeneratorDep, PackageWorkflowDep, TaskManagerDep
from app.models.application_package import ApplicationPackage
from app.scheduler.background import BackgroundTaskManager
from app.schemas.common import ERROR_RESPONSES, ErrorResponse, Page
from app.schemas.package import (
    AnswerRead,
    AnswerUpdate,
    ApprovePackageRequest,
    GeneratePackageRequest,
    PackageDetail,
    PackageStarted,
    PackageStatus,
    PackageSummary,
    RegeneratePackageRequest,
    RejectPackageRequest,
)
from app.services.package_service import PackageGenerator

router = APIRouter(prefix="/packages", tags=["packages"], responses=ERROR_RESPONSES)
NOT_FOUND: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorResponse, "description": "Package not found"},
    409: {"model": ErrorResponse, "description": "Not allowed in the package's current status"},
}


def _start(
    tasks: BackgroundTaskManager, generator: PackageGenerator, pkg: ApplicationPackage
) -> PackageStarted:
    package_id = pkg.id
    task = tasks.submit(
        "package-generation",
        lambda: generator.generate(package_id),
        dedupe_key=f"package:{package_id}",
    )
    return PackageStarted(
        package_id=package_id,
        task_id=task.id,
        status=task.status,
        detail="Generating the application package.",
    )


@router.post(
    "",
    response_model=PackageStarted,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Generate an application package for a job",
    responses={**NOT_FOUND, 422: {"model": ErrorResponse, "description": "Missing profile/resume"}},
)
async def generate_package(
    body: GeneratePackageRequest,
    workflow: PackageWorkflowDep,
    generator: PackageGeneratorDep,
    tasks: TaskManagerDep,
    db: DbSession,
) -> PackageStarted:
    pkg = await workflow.create(
        body.job_id, use_llm=body.use_llm, include_cover_letter=body.include_cover_letter
    )
    await db.commit()  # the background task reads the new row
    return _start(tasks, generator, pkg)


@router.get("", response_model=Page[PackageSummary], summary="Packages (the approval queue)")
async def list_packages(
    workflow: PackageWorkflowDep,
    status_: Annotated[
        list[PackageStatus] | None,
        Query(
            alias="status", description="Repeat to combine, e.g. status=generated&status=reviewed"
        ),
    ] = None,
    job_id: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[PackageSummary]:
    return await workflow.search(list(status_) if status_ else None, job_id, limit, offset)


@router.get(
    "/{package_id}",
    response_model=PackageDetail,
    summary="One package with everything in it",
    responses=NOT_FOUND,
)
async def get_package(package_id: uuid.UUID, workflow: PackageWorkflowDep) -> PackageDetail:
    return await workflow.detail(package_id)


@router.post(
    "/{package_id}/review",
    response_model=PackageDetail,
    summary="Mark the package as reviewed",
    responses=NOT_FOUND,
)
async def review_package(package_id: uuid.UUID, workflow: PackageWorkflowDep) -> PackageDetail:
    await workflow.review(package_id)
    return await workflow.detail(package_id)


@router.post(
    "/{package_id}/approve",
    response_model=PackageDetail,
    summary="Approve: the application becomes ready (approval mode)",
    responses=NOT_FOUND,
)
async def approve_package(
    package_id: uuid.UUID, workflow: PackageWorkflowDep, body: ApprovePackageRequest | None = None
) -> PackageDetail:
    await workflow.approve(package_id, (body or ApprovePackageRequest()).notes)
    return await workflow.detail(package_id)


@router.post(
    "/{package_id}/reject",
    response_model=PackageDetail,
    summary="Reject the package",
    responses=NOT_FOUND,
)
async def reject_package(
    package_id: uuid.UUID, body: RejectPackageRequest, workflow: PackageWorkflowDep
) -> PackageDetail:
    await workflow.reject(package_id, body.reason)
    return await workflow.detail(package_id)


@router.post(
    "/{package_id}/regenerate",
    response_model=PackageStarted,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Generate a new version (the current one is superseded)",
    responses=NOT_FOUND,
)
async def regenerate_package(
    package_id: uuid.UUID,
    workflow: PackageWorkflowDep,
    generator: PackageGeneratorDep,
    tasks: TaskManagerDep,
    db: DbSession,
    body: RegeneratePackageRequest | None = None,
) -> PackageStarted:
    body = body or RegeneratePackageRequest()
    pkg = await workflow.regenerate(
        package_id, use_llm=body.use_llm, include_cover_letter=body.include_cover_letter
    )
    await db.commit()
    return _start(tasks, generator, pkg)


@router.post(
    "/{package_id}/mark-submitted",
    response_model=PackageDetail,
    summary="Record that you applied with this package (nothing is sent)",
    responses=NOT_FOUND,
)
async def mark_submitted(package_id: uuid.UUID, workflow: PackageWorkflowDep) -> PackageDetail:
    await workflow.mark_submitted(package_id)
    return await workflow.detail(package_id)


@router.patch(
    "/{package_id}/answers/{answer_id}",
    response_model=AnswerRead,
    summary="Edit one answer",
    responses=NOT_FOUND,
)
async def update_answer(
    package_id: uuid.UUID, answer_id: uuid.UUID, body: AnswerUpdate, workflow: PackageWorkflowDep
) -> AnswerRead:
    return await workflow.update_answer(package_id, answer_id, body.answer)


@router.get(
    "/{package_id}/files/{doc}.{fmt}",
    summary="Download a generated PDF or DOCX",
    responses=NOT_FOUND,
)
async def download_file(
    package_id: uuid.UUID,
    doc: Literal["resume", "cover-letter", "original-resume"],
    fmt: Literal["pdf", "docx"],
    workflow: PackageWorkflowDep,
) -> Response:
    data, filename, content_type = await workflow.file(package_id, doc, fmt)
    return Response(
        content=data,
        media_type=content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"; '
            f"filename*=UTF-8''{quote(filename)}",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; sandbox",
            "Cache-Control": "no-store",
        },
    )
