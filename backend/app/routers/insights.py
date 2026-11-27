"""Insights router: analytics dashboard, company / resume / board analytics,
insights, recommendations and the Learning Agent (Phase 9).

All numbers come from your recorded applications and outcomes; with too
little data the endpoints say so instead of guessing."""

from typing import Annotated, Any

from fastapi import APIRouter, Path, Query

from app.dependencies import LearningDep
from app.schemas.common import ERROR_RESPONSES
from app.schemas.insights import (
    HistoryPoint,
    InsightsReport,
    RecommendationRead,
    RecommendationStateUpdate,
    RefreshResult,
)

router = APIRouter(prefix="/insights", tags=["insights"], responses=ERROR_RESPONSES)


@router.get("/summary", summary="Analytics dashboard")
async def summary(learning: LearningDep) -> dict[str, Any]:
    """Overview (rates with 95 % intervals), funnel, score accuracy, skill
    correlations, results by job family, workplace and score band."""
    return await learning.summary()


@router.get("/companies", summary="Company analytics")
async def companies(learning: LearningDep) -> list[dict[str, Any]]:
    return await learning.companies()


@router.get("/boards", summary="Job board analytics (Greenhouse, Lever, Ashby)")
async def boards(learning: LearningDep) -> list[dict[str, Any]]:
    return await learning.boards()


@router.get("/resumes", summary="Resume and package-style analytics")
async def resumes(learning: LearningDep) -> dict[str, Any]:
    return await learning.resumes()


@router.get("", response_model=InsightsReport, summary="Insights from your data")
async def insights(learning: LearningDep) -> InsightsReport:
    return InsightsReport.model_validate(await learning.insights())


@router.get("/recommendations", response_model=list[RecommendationRead], summary="Recommendations")
async def recommendations(
    learning: LearningDep, include_dismissed: bool = False
) -> list[RecommendationRead]:
    return [RecommendationRead.model_validate(r) for r in
            await learning.recommendations(include_dismissed)]  # fmt: skip


@router.put("/recommendations/{key}/state", summary="Dismiss, mark done, or restore")
async def set_recommendation_state(
    key: Annotated[str, Path(pattern=r"^[a-z0-9_:.-]{1,200}$")],
    body: RecommendationStateUpdate,
    learning: LearningDep,
) -> dict[str, Any]:
    return await learning.set_state(key, body.state, body.note)


@router.get("/history", response_model=list[HistoryPoint], summary="Learning history")
async def history(
    learning: LearningDep, limit: Annotated[int, Query(ge=1, le=365)] = 90
) -> list[HistoryPoint]:
    return [HistoryPoint.model_validate(p) for p in await learning.history(limit)]


@router.post("/refresh", response_model=RefreshResult, summary="Run the Learning Agent now")
async def refresh(learning: LearningDep) -> RefreshResult:
    return RefreshResult.model_validate(await learning.refresh("manual"))
