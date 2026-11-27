"""ORM: job_scores"""

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

from app.models.base import EMPTY_LIST, Base, CreatedAtMixin, UUIDPrimaryKeyMixin


class JobScore(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "job_scores"

    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )
    profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("candidate_profiles.id", ondelete="CASCADE"), nullable=False
    )
    overall_score: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    interview_probability: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    salary_score: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    growth_score: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    company_score: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    rationale: Mapped[str | None] = mapped_column(Text)
    matched_skills: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=EMPTY_LIST
    )
    missing_skills: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=EMPTY_LIST
    )
    model: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_version: Mapped[str] = mapped_column(Text, nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    __table_args__ = (
        CheckConstraint("overall_score BETWEEN 0 AND 100", name="ck_job_scores_overall"),
        CheckConstraint("interview_probability BETWEEN 0 AND 100", name="ck_job_scores_interview"),
        CheckConstraint("salary_score BETWEEN 0 AND 100", name="ck_job_scores_salary"),
        CheckConstraint("growth_score BETWEEN 0 AND 100", name="ck_job_scores_growth"),
        CheckConstraint("company_score BETWEEN 0 AND 100", name="ck_job_scores_company"),
        CheckConstraint("input_tokens >= 0 AND output_tokens >= 0", name="ck_job_scores_tokens"),
        CheckConstraint(
            "jsonb_typeof(matched_skills) = 'array' AND jsonb_typeof(missing_skills) = 'array'",
            name="ck_job_scores_skills_json",
        ),
        UniqueConstraint(
            "job_id", "profile_id", "prompt_version", name="uq_job_scores_job_profile_prompt"
        ),
        UniqueConstraint("id", "job_id", name="uq_job_scores_id_job"),
        Index("ix_job_scores_profile_overall", "profile_id", text("overall_score DESC")),
    )
