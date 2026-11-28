"""ORM: application_answers"""

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Numeric,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import EMPTY_LIST, Base, TimestampMixin, UUIDPrimaryKeyMixin


class ApplicationAnswer(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "application_answers"

    # Owner: the application, or (before one exists) the package.
    application_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("applications.id", ondelete="CASCADE")
    )
    package_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("application_packages.id", ondelete="CASCADE")
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    question_hash: Mapped[str] = mapped_column(Text, nullable=False)
    question_key: Mapped[str | None] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(3, 2))
    needs_review: Mapped[bool] = mapped_column(nullable=False, server_default=text("false"))
    evidence: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default=EMPTY_LIST)

    application = relationship("Application", back_populates="answers")

    __table_args__ = (
        CheckConstraint(
            "source IN ('profile', 'settings', 'rules', 'llm', 'user')",
            name="ck_application_answers_source",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_application_answers_confidence",
        ),
        CheckConstraint("question_hash ~ '^[0-9a-f]{64}$'", name="ck_application_answers_hash"),
        CheckConstraint(
            "num_nonnulls(application_id, package_id) = 1",
            name="ck_application_answers_one_owner",
        ),
        CheckConstraint(
            "jsonb_typeof(evidence) = 'array'", name="ck_application_answers_evidence_json"
        ),
        CheckConstraint("btrim(answer) <> ''", name="ck_application_answers_answer"),
        UniqueConstraint(
            "package_id", "question_hash", name="uq_application_answers_package_question"
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
