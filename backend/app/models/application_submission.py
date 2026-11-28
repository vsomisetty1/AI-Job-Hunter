"""ORM: application_submissions (one browser run of an approved package) and
automation_logs (its structured log lines). See migration 0006."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import (
    EMPTY_OBJECT,
    Base,
    CreatedAtMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)

SUBMISSION_STATUSES = (
    "queued", "in_progress", "waiting_for_review", "submitting", "submitted", "failed",
    "cancelled",
)  # fmt: skip
ACTIVE_STATUSES = ("queued", "in_progress", "waiting_for_review", "submitting")
FINAL_STATUSES = ("submitted", "failed", "cancelled")
STEPS = (
    "queued", "opening", "filling", "uploading", "validating", "review", "submitting",
    "confirming", "done",
)  # fmt: skip
ERROR_KINDS = (
    "browser_crash", "timeout", "network", "upload_failed", "validation_failed", "ats_changed",
    "captcha", "job_closed", "unconfirmed", "interrupted", "internal",
)  # fmt: skip
PLATFORMS = ("greenhouse", "lever", "ashby")
LOG_LEVELS = ("debug", "info", "warning", "error")
EMPTY_LIST = text("'[]'::jsonb")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


class ApplicationSubmission(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "application_submissions"

    application_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("applications.id", ondelete="CASCADE"), nullable=False
    )
    package_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("application_packages.id", ondelete="SET NULL")
    )
    platform: Mapped[str] = mapped_column(Text, nullable=False)
    apply_url: Mapped[str] = mapped_column(Text, nullable=False)
    mode: Mapped[str] = mapped_column(Text, nullable=False, server_default="APPROVAL_MODE")
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="queued")
    step: Mapped[str] = mapped_column(Text, nullable=False, server_default="queued")
    checkpoint: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=EMPTY_OBJECT
    )
    review: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=EMPTY_OBJECT
    )
    edits: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=EMPTY_OBJECT
    )
    screenshots: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=EMPTY_LIST
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    error: Mapped[str | None] = mapped_column(Text)
    error_kind: Mapped[str | None] = mapped_column(Text)
    confirmation_text: Mapped[str | None] = mapped_column(Text)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    queued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(_in("platform", PLATFORMS), name="ck_application_submissions_platform"),
        CheckConstraint("apply_url ~ '^https?://'", name="ck_application_submissions_apply_url"),
        CheckConstraint("mode IN ('APPROVAL_MODE')", name="ck_application_submissions_mode"),
        CheckConstraint(
            _in("status", SUBMISSION_STATUSES), name="ck_application_submissions_status"
        ),
        CheckConstraint(_in("step", STEPS), name="ck_application_submissions_step"),
        CheckConstraint(
            f"error_kind IS NULL OR {_in('error_kind', ERROR_KINDS)}",
            name="ck_application_submissions_error_kind",
        ),
        CheckConstraint("attempts >= 0", name="ck_application_submissions_attempts"),
        CheckConstraint(
            "jsonb_typeof(checkpoint) = 'object'",
            name="ck_application_submissions_checkpoint_json",
        ),
        CheckConstraint(
            "jsonb_typeof(review) = 'object'", name="ck_application_submissions_review_json"
        ),
        CheckConstraint(
            "jsonb_typeof(edits) = 'object'", name="ck_application_submissions_edits_json"
        ),
        CheckConstraint(
            "jsonb_typeof(screenshots) = 'array'",
            name="ck_application_submissions_screenshots_json",
        ),
        CheckConstraint(
            "status NOT IN ('submitting', 'submitted') OR confirmed_at IS NOT NULL",
            name="ck_application_submissions_confirmed",
        ),
        CheckConstraint(
            "status <> 'submitted' OR submitted_at IS NOT NULL",
            name="ck_application_submissions_submitted_at",
        ),
        CheckConstraint(
            "status <> 'failed' OR (failed_at IS NOT NULL AND error IS NOT NULL)",
            name="ck_application_submissions_failed",
        ),
        Index(
            "uq_application_submissions_active",
            "application_id",
            unique=True,
            postgresql_where=text(_in("status", ACTIVE_STATUSES)),
        ),
        Index("ix_application_submissions_application_id", "application_id", "created_at"),
        Index(
            "ix_application_submissions_package_id",
            "package_id",
            postgresql_where=text("package_id IS NOT NULL"),
        ),
        Index("ix_application_submissions_status", "status", "updated_at"),
    )


class AutomationLog(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "automation_logs"

    submission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("application_submissions.id", ondelete="CASCADE"),
        nullable=False,
    )
    level: Mapped[str] = mapped_column(Text, nullable=False, server_default="info")
    step: Mapped[str | None] = mapped_column(Text)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    detail: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=EMPTY_OBJECT
    )

    __table_args__ = (
        CheckConstraint(_in("level", LOG_LEVELS), name="ck_automation_logs_level"),
        CheckConstraint("btrim(message) <> ''", name="ck_automation_logs_message"),
        CheckConstraint("jsonb_typeof(detail) = 'object'", name="ck_automation_logs_detail_json"),
        Index("ix_automation_logs_submission_id", "submission_id", "created_at"),
        Index("ix_automation_logs_created_at", "created_at"),
        Index(
            "ix_automation_logs_level",
            "level",
            "created_at",
            postgresql_where=text("level IN ('warning', 'error')"),
        ),
    )
