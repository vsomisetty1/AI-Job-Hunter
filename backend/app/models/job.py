"""ORM: jobs"""
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import EMPTY_LIST, Base, TimestampMixin, UUIDPrimaryKeyMixin


class Job(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "jobs"

    source: Mapped[str] = mapped_column(Text, nullable=False)
    external_id: Mapped[str] = mapped_column(Text, nullable=False)
    company: Mapped[str] = mapped_column(Text, nullable=False)
    company_slug: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    location: Mapped[str | None] = mapped_column(Text)
    remote_type: Mapped[str] = mapped_column(Text, nullable=False, server_default="unknown")
    employment_type: Mapped[str | None] = mapped_column(Text)
    salary_min: Mapped[int | None] = mapped_column(Integer)
    salary_max: Mapped[int | None] = mapped_column(Integer)
    salary_currency: Mapped[str | None] = mapped_column(String(3))
    compensation_text: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    requirements: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=EMPTY_LIST
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    apply_url: Mapped[str | None] = mapped_column(Text)
    dedup_key: Mapped[str] = mapped_column(String(64), nullable=False)
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

    __table_args__ = (
        CheckConstraint("source ~ '^[a-z_]+$'", name="ck_jobs_source"),
        CheckConstraint(
            "remote_type IN ('remote', 'hybrid', 'onsite', 'unknown')", name="ck_jobs_remote_type"
        ),
        CheckConstraint(
            "status IN ('new', 'filtered', 'scored', 'shortlisted', 'skipped', 'applied', 'expired')",
            name="ck_jobs_status",
        ),
        CheckConstraint(
            "salary_min IS NULL OR salary_max IS NULL OR salary_min <= salary_max",
            name="ck_jobs_salary_range",
        ),
        CheckConstraint(
            "(salary_min IS NULL OR salary_min >= 0) AND (salary_max IS NULL OR salary_max >= 0)",
            name="ck_jobs_salary_nonneg",
        ),
        CheckConstraint("dedup_key ~ '^[0-9a-f]{64}$'", name="ck_jobs_dedup_key"),
        UniqueConstraint("source", "external_id", name="uq_jobs_source_external"),
        UniqueConstraint("url", name="uq_jobs_url"),
        Index("ix_jobs_status", "status"),
        Index("ix_jobs_dedup_key", "dedup_key"),
        Index("ix_jobs_company_lower", text("lower(company)")),
        Index("ix_jobs_source_slug", "source", "company_slug"),
        Index("ix_jobs_posted_at", text("posted_at DESC NULLS LAST")),
        Index("ix_jobs_last_seen_at", "last_seen_at"),
    )
