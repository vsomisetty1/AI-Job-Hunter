"""ORM: job_scores (one current row per job + profile + scoring method)"""

import uuid
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import EMPTY_LIST, EMPTY_OBJECT, Base, TimestampMixin, UUIDPrimaryKeyMixin


class JobScore(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "job_scores"

    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )
    profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("candidate_profiles.id", ondelete="CASCADE"), nullable=False
    )
    scoring_method: Mapped[str] = mapped_column(Text, nullable=False, server_default="rules")
    overall_score: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    skills_score: Mapped[int | None] = mapped_column(SmallInteger)
    seniority_score: Mapped[int | None] = mapped_column(SmallInteger)
    location_score: Mapped[int | None] = mapped_column(SmallInteger)
    relevance_score: Mapped[int | None] = mapped_column(SmallInteger)
    salary_score: Mapped[int | None] = mapped_column(SmallInteger)
    interview_probability: Mapped[int | None] = mapped_column(SmallInteger)
    growth_score: Mapped[int | None] = mapped_column(SmallInteger)
    company_score: Mapped[int | None] = mapped_column(SmallInteger)
    rationale: Mapped[str | None] = mapped_column(Text)
    matched_skills: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=EMPTY_LIST
    )
    missing_skills: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=EMPTY_LIST
    )
    breakdown: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=EMPTY_OBJECT
    )
    input_hash: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(Text)
    prompt_version: Mapped[str | None] = mapped_column(Text)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    __table_args__ = (
        CheckConstraint("scoring_method IN ('rules', 'claude')", name="ck_job_scores_method"),
        CheckConstraint("overall_score BETWEEN 0 AND 100", name="ck_job_scores_overall"),
        CheckConstraint("interview_probability BETWEEN 0 AND 100", name="ck_job_scores_interview"),
        CheckConstraint("salary_score BETWEEN 0 AND 100", name="ck_job_scores_salary"),
        CheckConstraint("growth_score BETWEEN 0 AND 100", name="ck_job_scores_growth"),
        CheckConstraint("company_score BETWEEN 0 AND 100", name="ck_job_scores_company"),
        CheckConstraint(
            "(skills_score IS NULL OR skills_score BETWEEN 0 AND 100) "
            "AND (seniority_score IS NULL OR seniority_score BETWEEN 0 AND 100) "
            "AND (location_score IS NULL OR location_score BETWEEN 0 AND 100) "
            "AND (relevance_score IS NULL OR relevance_score BETWEEN 0 AND 100)",
            name="ck_job_scores_components",
        ),
        CheckConstraint(
            "scoring_method <> 'claude' OR (model IS NOT NULL AND prompt_version IS NOT NULL)",
            name="ck_job_scores_claude_fields",
        ),
        CheckConstraint(
            "scoring_method <> 'rules' OR (input_tokens = 0 AND output_tokens = 0)",
            name="ck_job_scores_rules_no_tokens",
        ),
        CheckConstraint("input_tokens >= 0 AND output_tokens >= 0", name="ck_job_scores_tokens"),
        CheckConstraint(
            "jsonb_typeof(matched_skills) = 'array' AND jsonb_typeof(missing_skills) = 'array'",
            name="ck_job_scores_skills_json",
        ),
        CheckConstraint("jsonb_typeof(breakdown) = 'object'", name="ck_job_scores_breakdown_json"),
        CheckConstraint(
            "input_hash IS NULL OR input_hash ~ '^[0-9a-f]{64}$'", name="ck_job_scores_input_hash"
        ),
        UniqueConstraint(
            "job_id", "profile_id", "scoring_method", name="uq_job_scores_job_profile_method"
        ),
        UniqueConstraint("id", "job_id", name="uq_job_scores_id_job"),
        Index("ix_job_scores_profile_overall", "profile_id", text("overall_score DESC")),
    )
