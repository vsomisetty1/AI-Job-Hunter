"""Companies router: the job boards discovery crawls."""

import uuid
from typing import Any

from fastapi import APIRouter, Response, status

from app.dependencies import CompanyServiceDep
from app.models.company import Company
from app.schemas.common import ERROR_RESPONSES, ErrorResponse
from app.schemas.discovery import AddSuggestedRequest, DirectoryEntryRead
from app.schemas.job import CompanyCreate, CompanyRead, CompanyUpdate, CompanyWithStats

router = APIRouter(prefix="/companies", tags=["companies"], responses=ERROR_RESPONSES)
NOT_FOUND: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorResponse, "description": "Company not found"}
}


def _with_stats(company: Company, active: int = 0) -> CompanyWithStats:
    return CompanyWithStats(**CompanyRead.model_validate(company).model_dump(), active_jobs=active)


@router.get("", response_model=list[CompanyWithStats], summary="List tracked companies")
async def list_companies(service: CompanyServiceDep) -> list[CompanyWithStats]:
    return [_with_stats(c, n) for c, n in await service.list_companies()]


@router.get(
    "/directory",
    response_model=list[DirectoryEntryRead],
    summary="Suggested public job boards",
)
async def directory(service: CompanyServiceDep) -> list[dict[str, Any]]:
    return await service.directory()


@router.post(
    "",
    response_model=CompanyWithStats,
    status_code=status.HTTP_201_CREATED,
    summary="Track a company's job board (verified live)",
    responses={
        409: {"model": ErrorResponse, "description": "Board already tracked"},
        502: {"model": ErrorResponse, "description": "Job board unreachable"},
    },
)
async def add_company(body: CompanyCreate, service: CompanyServiceDep) -> CompanyWithStats:
    return _with_stats(await service.add(body))


@router.post(
    "/suggested",
    response_model=list[CompanyWithStats],
    status_code=status.HTTP_201_CREATED,
    summary="Track boards from the suggestions list",
)
async def add_suggested(
    body: AddSuggestedRequest, service: CompanyServiceDep
) -> list[CompanyWithStats]:
    added = await service.add_suggested([(b.source, b.slug.lower()) for b in body.boards])
    return [_with_stats(c) for c in added]


@router.patch(
    "/{company_id}",
    response_model=CompanyRead,
    summary="Rename or stop/start tracking",
    responses=NOT_FOUND,
)
async def update_company(
    company_id: uuid.UUID, body: CompanyUpdate, service: CompanyServiceDep
) -> Company:
    return await service.update(company_id, body)


@router.delete(
    "/{company_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a company with no jobs",
    responses=NOT_FOUND | {409: {"model": ErrorResponse, "description": "Company has jobs"}},
)
async def delete_company(company_id: uuid.UUID, service: CompanyServiceDep) -> Response:
    await service.delete(company_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
