"""ORM: discovery_runs (one row per job-board crawl)"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import EMPTY_LIST, Base

COUNTERS = (
    "companies_total", "companies_succeeded", "companies_failed", "jobs_found",
    "jobs_inserted", "jobs_updated", "jobs_unchanged", "jobs_skipped", "jobs_expired",
)  # fmt: skip


class DiscoveryRun(Base):
    __tablename__ = "discovery_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    trigger: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="running")
    companies_total: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    companies_succeeded: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    companies_failed: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    jobs_found: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    jobs_inserted: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    jobs_updated: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    jobs_unchanged: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    jobs_skipped: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    jobs_expired: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    error: Mapped[str | None] = mapped_column(Text)
    details: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=EMPTY_LIST
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint("trigger IN ('manual', 'scheduled')", name="ck_discovery_runs_trigger"),
        CheckConstraint(
            "status IN ('running', 'succeeded', 'partial', 'failed', 'cancelled')",
            name="ck_discovery_runs_status",
        ),
        CheckConstraint(
            " AND ".join(f"{c} >= 0" for c in COUNTERS), name="ck_discovery_runs_counts"
        ),
        CheckConstraint(
            "finished_at IS NULL OR finished_at >= started_at", name="ck_discovery_runs_finished"
        ),
        CheckConstraint(
            "status = 'running' OR finished_at IS NOT NULL",
            name="ck_discovery_runs_done_has_finish",
        ),
        CheckConstraint(
            "duration_ms IS NULL OR duration_ms >= 0", name="ck_discovery_runs_duration"
        ),
        CheckConstraint("jsonb_typeof(details) = 'array'", name="ck_discovery_runs_details_json"),
        Index("ix_discovery_runs_started_at", text("started_at DESC")),
        Index(
            "uq_discovery_runs_one_running",
            text("(true)"),
            unique=True,
            postgresql_where=text("status = 'running'"),
        ),
    )
