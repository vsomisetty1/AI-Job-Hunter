"""ORM: resumes"""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Resume(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "resumes"

    profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("candidate_profiles.id", ondelete="CASCADE"), nullable=False
    )
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    file_type: Mapped[str] = mapped_column(Text, nullable=False)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    raw_text: Mapped[str | None] = mapped_column(Text)
    parsed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_primary: Mapped[bool] = mapped_column(nullable=False, server_default=text("false"))

    profile = relationship("CandidateProfile", back_populates="resumes")
    versions = relationship("ResumeVersion", back_populates="resume", cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint("btrim(filename) <> ''", name="ck_resumes_filename"),
        CheckConstraint("file_type IN ('pdf', 'docx')", name="ck_resumes_file_type"),
        CheckConstraint("content_hash ~ '^[0-9a-f]{64}$'", name="ck_resumes_content_hash"),
        UniqueConstraint("profile_id", "content_hash", name="uq_resumes_profile_hash"),
        UniqueConstraint("storage_path", name="uq_resumes_storage_path"),
        Index(
            "uq_resumes_one_primary",
            "profile_id",
            unique=True,
            postgresql_where=text("is_primary"),
        ),
    )
