"""ORM: application_answers"""
import uuid
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Numeric,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ApplicationAnswer(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "application_answers"

    application_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("applications.id", ondelete="CASCADE"), nullable=False
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    question_hash: Mapped[str] = mapped_column(Text, nullable=False)
    question_key: Mapped[str | None] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(3, 2))
    needs_review: Mapped[bool] = mapped_column(nullable=False, server_default=text("false"))

    application = relationship("Application", back_populates="answers")

    __table_args__ = (
        CheckConstraint(
            "source IN ('profile', 'settings', 'llm', 'user')",
            name="ck_application_answers_source",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_application_answers_confidence",
        ),
        CheckConstraint(
            "question_hash ~ '^[0-9a-f]{64}$'", name="ck_application_answers_hash"
        ),
        UniqueConstraint(
            "application_id", "question_hash", name="uq_application_answers_app_question"
        ),
        Index(
            "ix_application_answers_needs_review",
            "application_id",
            postgresql_where=text("needs_review"),
        ),
    )
