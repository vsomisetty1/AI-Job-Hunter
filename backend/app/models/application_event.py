"""ORM: application_events (append-only audit trail)"""

import uuid
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import EMPTY_OBJECT, Base, CreatedAtMixin, UUIDPrimaryKeyMixin

_STATUSES = "('drafted', 'ready', 'submitted', 'interview', 'rejected', 'offer')"


class ApplicationEvent(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "application_events"

    application_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("applications.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    from_status: Mapped[str | None] = mapped_column(Text)
    to_status: Mapped[str | None] = mapped_column(Text)
    actor: Mapped[str] = mapped_column(Text, nullable=False, server_default="system")
    detail: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=EMPTY_OBJECT
    )

    application = relationship("Application", back_populates="events")

    __table_args__ = (
        CheckConstraint(
            "event_type IN ('created', 'status_changed', 'approved', 'automation_started', "
            "'checkpoint', 'retry', 'needs_manual', 'failed', 'submitted', 'note')",
            name="ck_application_events_type",
        ),
        CheckConstraint("actor IN ('system', 'user', 'agent')", name="ck_application_events_actor"),
        CheckConstraint(
            f"from_status IS NULL OR from_status IN {_STATUSES}",
            name="ck_application_events_from_status",
        ),
        CheckConstraint(
            f"to_status IS NULL OR to_status IN {_STATUSES}",
            name="ck_application_events_to_status",
        ),
        CheckConstraint(
            "jsonb_typeof(detail) = 'object'", name="ck_application_events_detail_json"
        ),
        Index("ix_application_events_app_created", "application_id", "created_at"),
    )
