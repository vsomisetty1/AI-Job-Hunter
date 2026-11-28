"""Applications router: the interview pipeline, outcome tracking and the
outcome timeline (Phase 9). Outcomes are entered by you; nothing here
contacts an employer or submits anything."""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Query, Response, status

from app.dependencies import OutcomeServiceDep
from app.schemas.common import ERROR_RESPONSES, ErrorResponse
from app.schemas.outcomes import (
    ApplicationOutcomes,
    ApplicationStatus,
    InterviewEventCreate,
    InterviewEventUpdate,
    PipelineItem,
    TimelineEntry,
)

router = APIRouter(prefix="/applications", tags=["applications"], responses=ERROR_RESPONSES)
NOT_FOUND: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorResponse, "description": "Application or event not found"},
    409: {"model": ErrorResponse, "description": "The application has not been submitted"},
}


@router.get("", response_model=list[PipelineItem], summary="Interview pipeline")
async def pipeline(
    outcomes: OutcomeServiceDep,
    status_: Annotated[list[ApplicationStatus] | None, Query(alias="status")] = None,
) -> list[PipelineItem]:
    """Submitted applications (by default) with their current stage and milestones."""
    return await outcomes.pipeline(list(status_) if status_ else None)


@router.get("/timeline", response_model=list[TimelineEntry], summary="Outcome timeline")
async def timeline(
    outcomes: OutcomeServiceDep, limit: Annotated[int, Query(ge=1, le=1000)] = 200
) -> list[TimelineEntry]:
    """Packages generated and approved, applications submitted and every
    recorded interview event, newest first."""
    return await outcomes.timeline(limit=limit)


@router.get(
    "/{application_id}", response_model=ApplicationOutcomes, summary="One application's outcomes",
    responses=NOT_FOUND,
)  # fmt: skip
async def detail(application_id: uuid.UUID, outcomes: OutcomeServiceDep) -> ApplicationOutcomes:
    return await outcomes.detail(application_id)


@router.post(
    "/{application_id}/events",
    response_model=ApplicationOutcomes,
    status_code=status.HTTP_201_CREATED,
    summary="Record a response, interview, offer, rejection or withdrawal",
    responses=NOT_FOUND,
)
async def add_event(
    application_id: uuid.UUID, body: InterviewEventCreate, outcomes: OutcomeServiceDep
) -> ApplicationOutcomes:
    return await outcomes.add_event(application_id, body)


@router.patch(
    "/{application_id}/events/{event_id}",
    response_model=ApplicationOutcomes,
    summary="Change an event (e.g. scheduled -> completed)",
    responses=NOT_FOUND,
)
async def update_event(
    application_id: uuid.UUID,
    event_id: uuid.UUID,
    body: InterviewEventUpdate,
    outcomes: OutcomeServiceDep,
) -> ApplicationOutcomes:
    return await outcomes.update_event(application_id, event_id, body)


@router.delete(
    "/{application_id}/events/{event_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Delete an event recorded by mistake",
    responses=NOT_FOUND,
)
async def delete_event(
    application_id: uuid.UUID, event_id: uuid.UUID, outcomes: OutcomeServiceDep
) -> Response:
    await outcomes.delete_event(application_id, event_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
