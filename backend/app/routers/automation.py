"""Application automation router (approval mode).

Start a run for an approved package (202), poll it until it waits for your
review, change fields, then submit with {"confirm": true}. Nothing is
submitted otherwise; there is no autonomous mode.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Query, Response, status

from app.dependencies import AutomationDep, TaskManagerDep
from app.scheduler.background import BackgroundTaskManager
from app.schemas.automation import (
    AutomationLogRead,
    AutomationQueue,
    AutomationStatus,
    FieldEditRequest,
    LogLevel,
    StartSubmissionRequest,
    SubmissionDetail,
    SubmissionStarted,
    SubmissionStatus,
    SubmissionSummary,
    SubmitRequest,
)
from app.schemas.common import ERROR_RESPONSES, ErrorResponse, Page
from app.services.automation_service import AutomationService

router = APIRouter(prefix="/automation", tags=["automation"], responses=ERROR_RESPONSES)
NOT_FOUND: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorResponse, "description": "Submission or package not found"},
    409: {"model": ErrorResponse, "description": "Not allowed in the run's current status"},
}


def _run(tasks: BackgroundTaskManager, automation: AutomationService, sid: uuid.UUID) -> str:
    return tasks.submit(
        "application-automation", lambda: automation.run(sid), dedupe_key=f"automation:{sid}"
    ).id


@router.get("/status", response_model=AutomationStatus, summary="Automation status")
async def automation_status(automation: AutomationDep) -> AutomationStatus:
    return automation.status()


@router.get("/queue", response_model=AutomationQueue, summary="Applications queue")
async def queue(automation: AutomationDep) -> AutomationQueue:
    """Approved packages ready to fill, runs in progress or waiting for you,
    and failed runs that need attention."""
    return await automation.queue()


@router.get("/submissions", response_model=Page[SubmissionSummary], summary="Submission history")
async def list_submissions(
    automation: AutomationDep,
    status_: Annotated[list[SubmissionStatus] | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[SubmissionSummary]:
    return await automation.history(list(status_) if status_ else None, limit, offset)


@router.post(
    "/submissions",
    response_model=SubmissionStarted,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Open and fill the application form for an approved package",
    responses={**NOT_FOUND, 422: {"model": ErrorResponse, "description": "Unsupported platform"}},
)
async def start_submission(
    body: StartSubmissionRequest, automation: AutomationDep, tasks: TaskManagerDep
) -> SubmissionStarted:
    sub = await automation.start(body.package_id)
    return SubmissionStarted(
        submission_id=sub.id,
        task_id=_run(tasks, automation, sub.id),
        status="queued",
        detail="Opening the application form. It will wait for your review; nothing is submitted.",
    )


@router.get(
    "/submissions/{submission_id}",
    response_model=SubmissionDetail,
    summary="Application review",
    responses=NOT_FOUND,
)
async def get_submission(submission_id: uuid.UUID, automation: AutomationDep) -> SubmissionDetail:
    return await automation.detail(submission_id)


@router.patch(
    "/submissions/{submission_id}/fields",
    response_model=SubmissionDetail,
    summary="Change one field in the open form",
    responses=NOT_FOUND,
)
async def edit_field(
    submission_id: uuid.UUID, body: FieldEditRequest, automation: AutomationDep
) -> SubmissionDetail:
    return await automation.edit(submission_id, body.key, body.value)


@router.post(
    "/submissions/{submission_id}/retry",
    response_model=SubmissionStarted,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Reopen and refill the form (resume from the checkpoint)",
    responses=NOT_FOUND,
)
async def retry_submission(
    submission_id: uuid.UUID, automation: AutomationDep, tasks: TaskManagerDep
) -> SubmissionStarted:
    await automation.retry(submission_id)
    return SubmissionStarted(
        submission_id=submission_id,
        task_id=_run(tasks, automation, submission_id),
        status="queued",
        detail="Reopening the form and refilling it with your edits.",
    )


@router.post(
    "/submissions/{submission_id}/cancel",
    response_model=SubmissionDetail,
    summary="Cancel the run (nothing is submitted)",
    responses=NOT_FOUND,
)
async def cancel_submission(
    submission_id: uuid.UUID, automation: AutomationDep
) -> SubmissionDetail:
    return await automation.cancel(submission_id)


@router.post(
    "/submissions/{submission_id}/submit",
    response_model=SubmissionStarted,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit the reviewed application (requires confirm: true)",
    responses=NOT_FOUND,
)
async def submit_submission(
    submission_id: uuid.UUID,
    body: SubmitRequest,
    automation: AutomationDep,
    tasks: TaskManagerDep,
) -> SubmissionStarted:
    assert body.confirm is True  # noqa: S101 - the schema only accepts true
    await automation.confirm_submit(submission_id)
    task = tasks.submit(
        "application-submit",
        lambda: automation.finish_submit(submission_id),
        dedupe_key=f"automation-submit:{submission_id}",
    )
    return SubmissionStarted(
        submission_id=submission_id,
        task_id=task.id,
        status="submitting",
        detail="Submitting the application you confirmed.",
    )


@router.get(
    "/submissions/{submission_id}/screenshots/{index}",
    summary="A screenshot taken during the run",
    response_class=Response,
    responses={200: {"content": {"image/png": {}}}, **NOT_FOUND},
)
async def screenshot(submission_id: uuid.UUID, index: int, automation: AutomationDep) -> Response:
    data = await automation.screenshot(submission_id, index)
    return Response(content=data, media_type="image/png",
                    headers={"Cache-Control": "private, max-age=3600"})  # fmt: skip


@router.get("/logs", response_model=Page[AutomationLogRead], summary="Automation logs")
async def logs(
    automation: AutomationDep,
    submission_id: uuid.UUID | None = None,
    level: Annotated[list[LogLevel] | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[AutomationLogRead]:
    return await automation.logs(
        submission_id=submission_id, levels=list(level) if level else None, limit=limit,
        offset=offset,
    )  # fmt: skip
