"""ORM: applications"""
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import (
    EMPTY_LIST,
    EMPTY_OBJECT,
    Base,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)


class Application(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "applications"

    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )
    profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("candidate_profiles.id", ondelete="CASCADE"), nullable=False
    )
    resume_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("resume_versions.id", ondelete="SET NULL")
    )
    cover_letter_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cover_letters.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="drafted")
    automation_state: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending")
    mode: Mapped[str] = mapped_column(Text, nullable=False, server_default="APPROVAL_MODE")
    platform: Mapped[str] = mapped_column(Text, nullable=False)
    match_score: Mapped[int | None] = mapped_column(SmallInteger)
    checkpoint: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=EMPTY_OBJECT
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text)
    confirmation_ref: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    status_history: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=EMPTY_LIST
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    answers = relationship(
        "ApplicationAnswer", back_populates="application", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('drafted', 'ready', 'submitted', 'interview', 'rejected', 'offer')",
            name="ck_applications_status",
        ),
        CheckConstraint(
            "automation_state IN ('pending', 'in_progress', 'needs_manual', 'failed', 'completed')",
            name="ck_applications_automation_state",
        ),
        CheckConstraint(
            "mode IN ('APPROVAL_MODE', 'AUTONOMOUS_MODE')", name="ck_applications_mode"
        ),
        CheckConstraint("platform ~ '^[a-z_]+$'", name="ck_applications_platform"),
        CheckConstraint(
            "match_score IS NULL OR match_score BETWEEN 0 AND 100",
            name="ck_applications_match_score",
        ),
        CheckConstraint("attempts >= 0", name="ck_applications_attempts"),
        CheckConstraint(
            "status IN ('drafted', 'ready') OR submitted_at IS NOT NULL",
            name="ck_applications_submitted_at",
        ),
        UniqueConstraint("job_id", "profile_id", name="uq_applications_job_profile"),
        Index("ix_applications_status", "status"),
        Index("ix_applications_automation_state", "automation_state"),
        Index("ix_applications_job_id", "job_id"),
        Index("ix_applications_submitted_at", text("submitted_at DESC NULLS LAST")),
    )
