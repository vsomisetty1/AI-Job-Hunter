"""Score schemas: the Claude scoring output, API read models, scoring runs."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import ORMModel

ScoringMethod = Literal["rules", "claude"]


# ------------------------------------------------------------- Claude output
class ClaudeJobScoreOutput(BaseModel):
    """What Claude returns for one job. Scores are clamped to 0-100 on save."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    overall_score: int = Field(description="Overall fit, 0-100")
    skills_score: int = Field(description="Skill fit, 0-100")
    seniority_score: int = Field(description="Level and experience fit, 0-100")
    interview_probability: int = Field(
        description="Chance, 0-100, that this candidate gets an interview if they apply"
    )
    growth_score: int = Field(description="Career growth this role offers the candidate, 0-100")
    company_score: int = Field(
        description="How attractive the company and team look from the posting, 0-100"
    )
    matched_skills: list[str] = Field(description="Skills the posting asks for that they have")
    missing_skills: list[str] = Field(
        description="Important skills the posting asks for that they lack"
    )
    strengths: list[str] = Field(description="1-3 reasons the candidate fits")
    concerns: list[str] = Field(description="0-3 reasons they may not")
    rationale: str = Field(description="Two sentences at most")


# --------------------------------------------------------------- API models
class JobScoreRead(ORMModel):
    id: uuid.UUID
    job_id: uuid.UUID
    profile_id: uuid.UUID
    scoring_method: ScoringMethod
    overall_score: int
    skills_score: int | None
    seniority_score: int | None
    location_score: int | None
    relevance_score: int | None
    salary_score: int | None
    interview_probability: int | None
    growth_score: int | None
    company_score: int | None
    rationale: str | None
    matched_skills: list[str]
    missing_skills: list[str]
    breakdown: dict[str, Any]
    model: str | None
    prompt_version: str | None
    input_tokens: int
    output_tokens: int
    created_at: datetime
    updated_at: datetime
    # False for a Claude score computed from older inputs (job, profile or
    # preferences changed since); it is shown but not used.
    is_current: bool = True


class FilterCheck(BaseModel):
    rule: str
    passed: bool
    reason: str


class FilterResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    passed: bool
    version: str
    checks: list[FilterCheck]


class ScoringStarted(BaseModel):
    task_id: str
    status: str
    detail: str


class ScoringSummary(BaseModel):
    """State of filtering and scoring for the dashboard and the Jobs page."""

    profile_id: uuid.UUID | None
    jobs_active: int
    jobs_unfiltered: int
    jobs_passed: int
    jobs_rejected: int
    jobs_duplicate: int
    jobs_scored: int
    jobs_claude_scored: int
    claude_available: bool
    claude_enabled: bool
    claude_calls_today: int
    claude_daily_limit: int
    last_run_at: datetime | None
    last_run_status: str | None
    task_running: bool
