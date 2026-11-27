"""Discovery router: start runs, follow them, connector health."""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Query, status

from app.dependencies import DiscoveryDep, PipelineDep, TaskManagerDep
from app.schemas.common import ERROR_RESPONSES, ErrorResponse, Page, PaginationParams
from app.schemas.discovery import (
    DiscoveryRunDetail,
    DiscoveryRunSummary,
    DiscoveryStarted,
    SourceHealth,
    StartDiscoveryRequest,
)

router = APIRouter(prefix="/discovery", tags=["discovery"], responses=ERROR_RESPONSES)
DISCOVERY_TASK_KEY = "discovery"


@router.post(
    "/runs",
    response_model=DiscoveryStarted,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start a discovery run now; found jobs are then deduplicated, filtered and scored",
    responses={409: {"model": ErrorResponse, "description": "A run is already in progress"}},
)
async def start_run(
    discovery: DiscoveryDep,
    pipeline: PipelineDep,
    tasks: TaskManagerDep,
    body: StartDiscoveryRequest | None = None,
) -> DiscoveryStarted:
    body = body or StartDiscoveryRequest()
    run_id = await discovery.start("manual")  # 409 while another run is going
    task = tasks.submit(
        "job-discovery",
        lambda: pipeline.execute(run_id, company_ids=body.company_ids, only_due=body.only_due),
        dedupe_key=DISCOVERY_TASK_KEY,
    )
    return DiscoveryStarted(
        run_id=run_id, task_id=task.id, status=task.status, detail="Discovery started."
    )


@router.get("/runs", response_model=Page[DiscoveryRunSummary], summary="Recent discovery runs")
async def list_runs(
    page: Annotated[PaginationParams, Query()], discovery: DiscoveryDep
) -> Page[DiscoveryRunSummary]:
    runs, total = await discovery.recent_runs(limit=page.limit, offset=page.offset)
    return Page[DiscoveryRunSummary](
        items=[DiscoveryRunSummary.model_validate(r) for r in runs],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get(
    "/runs/{run_id}",
    response_model=DiscoveryRunDetail,
    summary="One run, with per-company results",
    responses={404: {"model": ErrorResponse, "description": "Run not found"}},
)
async def get_run(run_id: uuid.UUID, discovery: DiscoveryDep) -> Any:
    return await discovery.get_run(run_id)


@router.get("/health", response_model=list[SourceHealth], summary="Connector health")
async def connector_health(
    discovery: DiscoveryDep,
    probe: Annotated[bool, Query(description="Also call each platform's API live.")] = False,
) -> list[dict[str, Any]]:
    return await discovery.health(probe=probe)
