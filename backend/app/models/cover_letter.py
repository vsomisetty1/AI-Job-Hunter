"""ORM: cover_letters"""
import uuid

from sqlalchemy import CheckConstraint, ForeignKey, Index, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


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

    __table_args__ = (
        CheckConstraint("btrim(content) <> ''", name="ck_cover_letters_content"),
        UniqueConstraint("job_id", "profile_id", name="uq_cover_letters_job_profile"),
        UniqueConstraint("id", "job_id", name="uq_cover_letters_id_job"),
        Index("ix_cover_letters_profile_id", "profile_id"),
    )
