"""ORM: cover_letters"""

import uuid
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import EMPTY_OBJECT, Base, TimestampMixin, UUIDPrimaryKeyMixin


class CoverLetter(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "cover_letters"

    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )
    profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("candidate_profiles.id", ondelete="CASCADE"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    pdf_path: Mapped[str | None] = mapped_column(Text)
    docx_path: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(Text)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    word_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    method: Mapped[str] = mapped_column(Text, nullable=False, server_default="rules")
    generation: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=EMPTY_OBJECT
    )

    __table_args__ = (
        CheckConstraint("btrim(content) <> ''", name="ck_cover_letters_content"),
        CheckConstraint("version_number >= 1", name="ck_cover_letters_version"),
        CheckConstraint("word_count >= 0", name="ck_cover_letters_word_count"),
        CheckConstraint("method IN ('rules', 'claude')", name="ck_cover_letters_method"),
        CheckConstraint(
            "jsonb_typeof(generation) = 'object'", name="ck_cover_letters_generation_json"
        ),
        UniqueConstraint(
            "job_id", "profile_id", "version_number", name="uq_cover_letters_job_profile_version"
        ),
        UniqueConstraint("id", "job_id", name="uq_cover_letters_id_job"),
        Index("ix_cover_letters_profile_id", "profile_id"),
    )
