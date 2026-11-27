"""Jobs router: search discovered jobs, view one, inspect its raw board payload."""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Query

from app.dependencies import JobServiceDep
from app.schemas.common import ERROR_RESPONSES, ErrorResponse, Page
from app.schemas.job import JobDetail, JobSearchParams, JobSummary

router = APIRouter(prefix="/jobs", tags=["jobs"], responses=ERROR_RESPONSES)
NOT_FOUND: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorResponse, "description": "Job not found"}
}


@router.get("", response_model=Page[JobSummary], summary="Search discovered jobs")
async def search_jobs(
    params: Annotated[JobSearchParams, Query()], service: JobServiceDep
) -> Page[JobSummary]:
    return await service.search(params)


@router.get("/stats", summary="Job counts by source, status and remote type")
async def job_stats(service: JobServiceDep) -> dict[str, dict[str, int]]:
    return await service.stats()


@router.get("/{job_id}", response_model=JobDetail, summary="Get a job", responses=NOT_FOUND)
async def get_job(job_id: uuid.UUID, service: JobServiceDep) -> JobDetail:
    return await service.detail(job_id)


@router.get(
    "/{job_id}/raw",
    summary="The job exactly as the board returned it",
    responses=NOT_FOUND,
)
async def get_job_raw(job_id: uuid.UUID, service: JobServiceDep) -> dict[str, Any]:
    return await service.raw(job_id)
