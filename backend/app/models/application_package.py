"""ORM: application_packages (tailored resume + cover letter + answers for one job)"""

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
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import EMPTY_OBJECT, Base, TimestampMixin, UUIDPrimaryKeyMixin

PACKAGE_STATUSES = (
    "generating", "generated", "reviewed", "approved", "rejected", "submitted", "failed",
    "superseded",
)  # fmt: skip
LIVE_STATUSES = ("generating", "generated", "reviewed", "approved", "submitted")


class ApplicationPackage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "application_packages"

    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )
    profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("candidate_profiles.id", ondelete="CASCADE"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="generating")
    job_score_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    base_resume_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("resume_versions.id", ondelete="SET NULL")
    )
    resume_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    cover_letter_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    application_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("applications.id", ondelete="SET NULL")
    )
    score_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=EMPTY_OBJECT
    )
    generation: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=EMPTY_OBJECT
    )
    error: Mapped[str | None] = mapped_column(Text)
    review_notes: Mapped[str | None] = mapped_column(Text)
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        ForeignKeyConstraint(
            ["job_score_id", "job_id"],
            ["job_scores.id", "job_scores.job_id"],
            ondelete="SET NULL (job_score_id)",
            name="fk_application_packages_job_score_id",
        ),
        ForeignKeyConstraint(
            ["resume_version_id", "job_id"],
            ["resume_versions.id", "resume_versions.job_id"],
            ondelete="SET NULL (resume_version_id)",
            name="fk_application_packages_resume_version_id",
        ),
        ForeignKeyConstraint(
            ["cover_letter_id", "job_id"],
            ["cover_letters.id", "cover_letters.job_id"],
            ondelete="SET NULL (cover_letter_id)",
            name="fk_application_packages_cover_letter_id",
        ),
        CheckConstraint(
            "status IN (" + ", ".join(f"'{s}'" for s in PACKAGE_STATUSES) + ")",
            name="ck_application_packages_status",
        ),
        CheckConstraint("version_number >= 1", name="ck_application_packages_version"),
        CheckConstraint(
            "jsonb_typeof(score_snapshot) = 'object'", name="ck_application_packages_score_json"
        ),
        CheckConstraint(
            "jsonb_typeof(generation) = 'object'", name="ck_application_packages_generation_json"
        ),
        CheckConstraint(
            "status IN ('generating', 'failed') OR generated_at IS NOT NULL",
            name="ck_application_packages_generated",
        ),
        CheckConstraint(
            "status NOT IN ('approved', 'submitted') OR approved_at IS NOT NULL",
            name="ck_application_packages_approved",
        ),
        CheckConstraint(
            "status <> 'rejected' OR rejected_at IS NOT NULL",
            name="ck_application_packages_rejected",
        ),
        CheckConstraint(
            "status <> 'submitted' OR submitted_at IS NOT NULL",
            name="ck_application_packages_submitted",
        ),
        CheckConstraint(
            "status <> 'failed' OR error IS NOT NULL", name="ck_application_packages_failed"
        ),
        UniqueConstraint(
            "job_id",
            "profile_id",
            "version_number",
            name="uq_application_packages_job_profile_version",
        ),  # fmt: skip
        Index(
            "uq_application_packages_live",
            "job_id",
            "profile_id",
            unique=True,
            postgresql_where=text("status IN (" + ", ".join(f"'{s}'" for s in LIVE_STATUSES) + ")"),
        ),
        Index("ix_application_packages_status_created", "status", text("created_at DESC")),
        Index("ix_application_packages_profile_id", "profile_id"),
        *(
            Index(
                f"ix_application_packages_{col}", col, postgresql_where=text(f"{col} IS NOT NULL")
            )
            for col in (
                "job_score_id",
                "resume_version_id",
                "base_resume_version_id",
                "cover_letter_id",
                "application_id",
            )
        ),  # fmt: skip
    )


def a_status(status: str) -> str:
    """'An approved', 'A generated': the status with its article, for messages."""
    return ("An " if status[:1] in "aeiou" else "A ") + status
