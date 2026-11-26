"""ORM: resume_versions"""
import uuid
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import (
    EMPTY_ARRAY,
    EMPTY_OBJECT,
    Base,
    CreatedAtMixin,
    UUIDPrimaryKeyMixin,
    text_array,
)


class ResumeVersion(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "resume_versions"

    resume_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("resumes.id", ondelete="CASCADE"), nullable=False
    )
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE")
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False, server_default="tailored")
    version_number: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    content: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=EMPTY_OBJECT
    )
    pdf_path: Mapped[str | None] = mapped_column(Text)
    docx_path: Mapped[str | None] = mapped_column(Text)
    ats_keywords: Mapped[list[str]] = mapped_column(
        text_array(), nullable=False, server_default=EMPTY_ARRAY
    )
    change_summary: Mapped[str | None] = mapped_column(Text)

    resume = relationship("Resume", back_populates="versions")

    __table_args__ = (
        CheckConstraint("kind IN ('original', 'tailored')", name="ck_resume_versions_kind"),
        CheckConstraint("version_number >= 1", name="ck_resume_versions_version"),
        CheckConstraint(
            "kind = 'original' OR job_id IS NOT NULL", name="ck_resume_versions_tailored_has_job"
        ),
        UniqueConstraint(
            "resume_id", "job_id", "version_number", name="uq_resume_versions_resume_job_version"
        ),
        Index("ix_resume_versions_resume_id", "resume_id"),
        Index("ix_resume_versions_job_id", "job_id"),
    )
