"""Learning and insights API (Phase 9). Analytics payloads are plain JSON
objects documented in docs (rates are {k, n, rate, low, high} with a 95 %
Wilson interval)."""

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.common import APIModel


class InsightRead(BaseModel):
    key: str
    kind: Literal["comparison", "threshold", "skill", "score", "fact"]
    title: str
    detail: str
    confidence: Literal["high", "medium", "low", "fact"]
    direction: Literal["better", "worse", "neutral"]
    dimension: str | None = None
    segment: str | None = None
    outcome: str | None = None
    evidence: dict[str, Any] = Field(default_factory=dict)


class InsightsReport(BaseModel):
    status: Literal["ok", "insufficient_data"]
    message: str
    comparisons_tested: int
    insights: list[InsightRead]


class RecommendationRead(BaseModel):
    key: str
    category: Literal["targeting", "profile", "process", "data"]
    priority: Literal["high", "medium", "low"]
    title: str
    rationale: str
    action_label: str
    action_href: str
    based_on: list[str] = Field(default_factory=list)
    evidence: dict[str, Any] = Field(default_factory=dict)
    state: Literal["dismissed", "done"] | None = None


class RecommendationStateUpdate(APIModel):
    # null clears the state (the recommendation shows again).
    state: Literal["dismissed", "done"] | None
    note: str | None = Field(default=None, max_length=500)


class HistoryPoint(BaseModel):
    at: str
    submitted: int | None
    response_rate: float | None
    interview_rate: float | None
    offer_rate: float | None
    insights: int
    recommendations: int


class RefreshResult(BaseModel):
    stored: bool
    records: int
    computed_at: str
