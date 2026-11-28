"""ORM: applications

Composite FKs guarantee the attached resume version, cover letter and score
belong to the same job as the application. ON DELETE SET NULL (column) needs
PostgreSQL 15+.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import EMPTY_OBJECT, Base, TimestampMixin, UUIDPrimaryKeyMixin


class Application(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "applications"

    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="RESTRICT"), nullable=False
    )
    profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("candidate_profiles.id", ondelete="CASCADE"), nullable=False
    )
    resume_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    cover_letter_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    job_score_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="drafted")
    automation_state: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending")
    application_mode: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="APPROVAL_MODE"
    )
    checkpoint: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=EMPTY_OBJECT
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text)
    confirmation_ref: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Outcome milestones, derived from interview_events (Phase 9).
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_interview_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    offer_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    answers = relationship(
        "ApplicationAnswer", back_populates="application", cascade="all, delete-orphan"
    )
    events = relationship(
        "ApplicationEvent",
        back_populates="application",
        cascade="all, delete-orphan",
        order_by="ApplicationEvent.created_at",
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["resume_version_id", "job_id"],
            ["resume_versions.id", "resume_versions.job_id"],
            ondelete="SET NULL (resume_version_id)",
        ),
        ForeignKeyConstraint(
            ["cover_letter_id", "job_id"],
            ["cover_letters.id", "cover_letters.job_id"],
            ondelete="SET NULL (cover_letter_id)",
        ),
        ForeignKeyConstraint(
            ["job_score_id", "job_id"],
            ["job_scores.id", "job_scores.job_id"],
            ondelete="SET NULL (job_score_id)",
        ),
        CheckConstraint(
            "status IN ('drafted', 'ready', 'submitted', 'interview', 'rejected', 'offer', "
            "'withdrawn')",
            name="ck_applications_status",
        ),
        CheckConstraint(
            "automation_state IN ('pending', 'in_progress', 'needs_manual', 'failed', 'completed')",
            name="ck_applications_automation_state",
        ),
        CheckConstraint(
            "application_mode IN ('APPROVAL_MODE', 'AUTONOMOUS_MODE')", name="ck_applications_mode"
        ),
        CheckConstraint("attempts >= 0", name="ck_applications_attempts"),
        CheckConstraint(
            "jsonb_typeof(checkpoint) = 'object'", name="ck_applications_checkpoint_json"
        ),
        CheckConstraint(
            "status IN ('drafted', 'ready') OR submitted_at IS NOT NULL",
            name="ck_applications_submitted_at",
        ),
        CheckConstraint(
            "automation_state <> 'completed' OR submitted_at IS NOT NULL",
            name="ck_applications_completed_submitted",
        ),
        CheckConstraint(
            "submitted_at IS NOT NULL OR (responded_at IS NULL AND first_interview_at IS NULL "
            "AND offer_at IS NULL AND rejected_at IS NULL AND withdrawn_at IS NULL)",
            name="ck_applications_outcomes_after_submit",
        ),
        UniqueConstraint("job_id", "profile_id", name="uq_applications_job_profile"),
        Index("ix_applications_status_updated", "status", text("status_updated_at DESC")),
        Index(
            "ix_applications_open_work",
            "automation_state",
            "created_at",
            postgresql_where=text("automation_state <> 'completed'"),
        ),
        Index("ix_applications_submitted_at", text("submitted_at DESC NULLS LAST")),
        Index("ix_applications_profile_id", "profile_id"),
        Index(
            "ix_applications_resume_version_id",
            "resume_version_id",
            postgresql_where=text("resume_version_id IS NOT NULL"),
        ),
        Index(
            "ix_applications_cover_letter_id",
            "cover_letter_id",
            postgresql_where=text("cover_letter_id IS NOT NULL"),
        ),
        Index(
            "ix_applications_job_score_id",
            "job_score_id",
            postgresql_where=text("job_score_id IS NOT NULL"),
        ),
    )
