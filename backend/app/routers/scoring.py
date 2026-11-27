"""Scoring router: re-run filtering and scoring, and see where they stand."""

from fastapi import APIRouter, status

from app.dependencies import PipelineDep, ScoringDep, TaskManagerDep
from app.scheduler.background import BackgroundTaskManager
from app.schemas.common import ERROR_RESPONSES
from app.schemas.job_score import ScoringStarted, ScoringSummary
from app.services.pipeline_service import JobPipeline

router = APIRouter(prefix="/scoring", tags=["scoring"], responses=ERROR_RESPONSES)
SCORING_TASK_KEY = "scoring"


def start_rescore(tasks: BackgroundTaskManager, pipeline: JobPipeline) -> ScoringStarted:
    """Queue deduplicate + filter + score (a second request joins the running task)."""
    task = tasks.submit("job-scoring", pipeline.rescore, dedupe_key=SCORING_TASK_KEY)
    return ScoringStarted(
        task_id=task.id, status=task.status, detail="Filtering and scoring started."
    )


@router.post(
    "/runs",
    response_model=ScoringStarted,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Filter and score the stored jobs again now",
)
async def start_scoring(pipeline: PipelineDep, tasks: TaskManagerDep) -> ScoringStarted:
    return start_rescore(tasks, pipeline)


@router.get("/summary", response_model=ScoringSummary, summary="Filtering and scoring status")
async def scoring_summary(
    scoring: ScoringDep, pipeline: PipelineDep, tasks: TaskManagerDep
) -> ScoringSummary:
    running = any(t.dedupe_key == SCORING_TASK_KEY and not t.done for t in tasks.list_tasks())
    return await scoring.summary(task_running=running or pipeline.busy)
