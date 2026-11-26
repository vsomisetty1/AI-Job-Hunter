"""ORM: jobs (source and company name come from the owning Company)"""
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import EMPTY_LIST, Base, TimestampMixin, UUIDPrimaryKeyMixin


class Job(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "jobs"

    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False
    )
    external_id: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    location: Mapped[str | None] = mapped_column(Text)
    remote_type: Mapped[str] = mapped_column(Text, nullable=False, server_default="unknown")
    employment_type: Mapped[str | None] = mapped_column(Text)
    salary_min: Mapped[int | None] = mapped_column(Integer)
    salary_max: Mapped[int | None] = mapped_column(Integer)
    salary_currency: Mapped[str | None] = mapped_column(Text)
    compensation_text: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    requirements: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=EMPTY_LIST
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    apply_url: Mapped[str | None] = mapped_column(Text)
    dedup_key: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="new")
    filter_reason: Mapped[str | None] = mapped_column(Text)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    raw: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    company = relationship("Company", back_populates="jobs")

    __table_args__ = (
        CheckConstraint("btrim(external_id) <> ''", name="ck_jobs_external_id"),
        CheckConstraint("btrim(title) <> ''", name="ck_jobs_title"),
        CheckConstraint(
            "remote_type IN ('remote', 'hybrid', 'onsite', 'unknown')", name="ck_jobs_remote_type"
        ),
        CheckConstraint(
            "status IN ('new', 'filtered', 'scored', 'shortlisted', 'skipped', 'applied', "
            "'expired')",
            name="ck_jobs_status",
        ),
        CheckConstraint("url ~ '^https?://'", name="ck_jobs_url"),
        CheckConstraint("apply_url IS NULL OR apply_url ~ '^https?://'", name="ck_jobs_apply_url"),
        CheckConstraint(
            "salary_min IS NULL OR salary_max IS NULL OR salary_min <= salary_max",
            name="ck_jobs_salary_range",
        ),
        CheckConstraint(
            "(salary_min IS NULL OR salary_min >= 0) AND (salary_max IS NULL OR salary_max >= 0)",
            name="ck_jobs_salary_nonneg",
        ),
        CheckConstraint(
            "salary_currency IS NULL OR salary_currency ~ '^[A-Z]{3}$'", name="ck_jobs_currency"
        ),
        CheckConstraint("dedup_key ~ '^[0-9a-f]{64}$'", name="ck_jobs_dedup_key"),
        CheckConstraint("jsonb_typeof(requirements) = 'array'", name="ck_jobs_requirements_json"),
        CheckConstraint("raw IS NULL OR jsonb_typeof(raw) = 'object'", name="ck_jobs_raw_json"),
        CheckConstraint("last_seen_at >= first_seen_at", name="ck_jobs_seen_order"),
        UniqueConstraint("company_id", "external_id", name="uq_jobs_company_external"),
        UniqueConstraint("url", name="uq_jobs_url"),
        Index("ix_jobs_status_first_seen", "status", "first_seen_at"),
        Index("ix_jobs_dedup_key", "dedup_key"),
        Index("ix_jobs_company_last_seen", "company_id", "last_seen_at"),
        Index("ix_jobs_posted_at", text("posted_at DESC NULLS LAST")),
    )
