"""ORM: interview_events (what happened after applying), learning_snapshots
(the Learning Agent's computed history) and recommendation_states. See
migration 0007."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import (
    EMPTY_OBJECT,
    Base,
    CreatedAtMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)

# Order of the hiring process (offer, rejection and withdrawal end it).
INTERVIEW_STAGES = (
    "recruiter_response", "recruiter_screen", "phone_screen", "technical_interview",
    "hiring_manager_interview", "onsite", "final_round", "offer", "rejection", "withdrawal",
)  # fmt: skip
INTERVIEW_ROUNDS = (
    "recruiter_screen", "phone_screen", "technical_interview", "hiring_manager_interview",
    "onsite", "final_round",
)  # fmt: skip
TERMINAL_STAGES = ("offer", "rejection", "withdrawal")
EVENT_STATUSES = ("scheduled", "completed", "cancelled", "no_show")
RECOMMENDATION_STATUSES = ("dismissed", "done")
EMPTY_LIST = text("'[]'::jsonb")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


class InterviewEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "interview_events"

    application_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("applications.id", ondelete="CASCADE"), nullable=False
    )
    stage: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="completed")
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint(_in("stage", INTERVIEW_STAGES), name="ck_interview_events_stage"),
        CheckConstraint(_in("status", EVENT_STATUSES), name="ck_interview_events_status"),
        CheckConstraint(
            "stage NOT IN ('recruiter_response', 'offer', 'rejection', 'withdrawal') "
            "OR status = 'completed'",
            name="ck_interview_events_terminal_completed",
        ),
        CheckConstraint("notes IS NULL OR length(notes) <= 4000", name="ck_interview_events_notes"),
        Index("ix_interview_events_application_id", "application_id", "occurred_at"),
        Index("ix_interview_events_stage", "stage", "occurred_at"),
    )


class LearningSnapshot(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "learning_snapshots"

    data_hash: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=EMPTY_OBJECT
    )
    insights: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default=EMPTY_LIST)
    recommendations: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=EMPTY_LIST
    )

    __table_args__ = (
        CheckConstraint("data_hash ~ '^[0-9a-f]{64}$'", name="ck_learning_snapshots_hash"),
        CheckConstraint(
            "jsonb_typeof(summary) = 'object'", name="ck_learning_snapshots_summary_json"
        ),
        CheckConstraint(
            "jsonb_typeof(insights) = 'array'", name="ck_learning_snapshots_insights_json"
        ),
        CheckConstraint(
            "jsonb_typeof(recommendations) = 'array'",
            name="ck_learning_snapshots_recommendations_json",
        ),
        Index("ix_learning_snapshots_created_at", "created_at"),
    )


class RecommendationState(Base):
    __tablename__ = "recommendation_states"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )

    __table_args__ = (
        CheckConstraint("key ~ '^[a-z0-9_:.-]{1,200}$'", name="ck_recommendation_states_key"),
        CheckConstraint(
            _in("status", RECOMMENDATION_STATUSES), name="ck_recommendation_states_status"
        ),
    )
