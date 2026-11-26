"""ORM: agent_runs"""
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, Numeric, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import EMPTY_OBJECT, Base, UUIDPrimaryKeyMixin


class AgentRun(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "agent_runs"

    agent_name: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="running")
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="SET NULL")
    )
    application_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("applications.id", ondelete="SET NULL")
    )
    input_summary: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=EMPTY_OBJECT
    )
    output_summary: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=EMPTY_OBJECT
    )
    error: Mapped[str | None] = mapped_column(Text)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False, server_default="0")
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)

    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'succeeded', 'failed', 'cancelled')",
            name="ck_agent_runs_status",
        ),
        CheckConstraint("input_tokens >= 0 AND output_tokens >= 0", name="ck_agent_runs_tokens"),
        CheckConstraint("btrim(agent_name) <> ''", name="ck_agent_runs_name"),
        CheckConstraint("cost_usd >= 0", name="ck_agent_runs_cost"),
        CheckConstraint("duration_ms IS NULL OR duration_ms >= 0", name="ck_agent_runs_duration"),
        CheckConstraint(
            "status = 'running' OR finished_at IS NOT NULL", name="ck_agent_runs_done_has_finish"
        ),
        CheckConstraint(
            "jsonb_typeof(input_summary) = 'object' AND jsonb_typeof(output_summary) = 'object'",
            name="ck_agent_runs_summaries_json",
        ),
        CheckConstraint(
            "finished_at IS NULL OR finished_at >= started_at", name="ck_agent_runs_finished"
        ),
        Index("ix_agent_runs_agent_started", "agent_name", text("started_at DESC")),
        Index("ix_agent_runs_started_at", "started_at"),
        Index("ix_agent_runs_status", "status"),
        Index("ix_agent_runs_job_id", "job_id", postgresql_where=text("job_id IS NOT NULL")),
        Index(
            "ix_agent_runs_application_id",
            "application_id",
            postgresql_where=text("application_id IS NOT NULL"),
        ),
    )
