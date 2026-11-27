"""ORM: resume_versions (tailored resume per job)"""

import uuid
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import (
    EMPTY_ARRAY,
    EMPTY_LIST,
    EMPTY_OBJECT,
    Base,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    text_array,
)


class ResumeVersion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "resume_versions"

    resume_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("resumes.id", ondelete="CASCADE"), nullable=False
    )
    # original: uploaded file; parsed: structured data; tailored: for a target
    kind: Mapped[str] = mapped_column(Text, nullable=False, server_default="tailored")
    source: Mapped[str] = mapped_column(Text, nullable=False, server_default="tailoring")
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE")
    )
    target_role: Mapped[str | None] = mapped_column(Text)
    target_company: Mapped[str | None] = mapped_column(Text)
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
    base_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("resume_versions.id", ondelete="SET NULL")
    )
    changes: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default=EMPTY_LIST)
    tailoring: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=EMPTY_OBJECT
    )

    resume = relationship("Resume", back_populates="versions")

    __table_args__ = (
        CheckConstraint("version_number >= 1", name="ck_resume_versions_version"),
        CheckConstraint("jsonb_typeof(content) = 'object'", name="ck_resume_versions_content_json"),
        CheckConstraint("jsonb_typeof(changes) = 'array'", name="ck_resume_versions_changes_json"),
        CheckConstraint(
            "jsonb_typeof(tailoring) = 'object'", name="ck_resume_versions_tailoring_json"
        ),
        CheckConstraint(
            "base_version_id IS NULL OR kind = 'tailored'",
            name="ck_resume_versions_base_only_tailored",
        ),
        CheckConstraint(
            "kind IN ('original', 'parsed', 'tailored')", name="ck_resume_versions_kind"
        ),
        CheckConstraint(
            "source IN ('upload', 'parser', 'user_edit', 'tailoring')",
            name="ck_resume_versions_source",
        ),
        CheckConstraint(
            "kind = 'tailored' "
            "OR (job_id IS NULL AND target_role IS NULL AND target_company IS NULL)",
            name="ck_resume_versions_untailored_no_target",
        ),
        CheckConstraint(
            "kind <> 'tailored' OR job_id IS NOT NULL OR target_role IS NOT NULL",
            name="ck_resume_versions_tailored_has_target",
        ),
        CheckConstraint(
            "target_role IS NULL OR btrim(target_role) <> ''",
            name="ck_resume_versions_target_role",
        ),
        CheckConstraint(
            "target_company IS NULL OR btrim(target_company) <> ''",
            name="ck_resume_versions_target_company",
        ),
        UniqueConstraint("resume_id", "version_number", name="uq_resume_versions_resume_version"),
        UniqueConstraint("id", "job_id", name="uq_resume_versions_id_job"),
        Index("ix_resume_versions_job_id", "job_id"),
        Index("ix_resume_versions_resume_kind", "resume_id", "kind", text("version_number DESC")),
        Index(
            "ix_resume_versions_base_version_id",
            "base_version_id",
            postgresql_where=text("base_version_id IS NOT NULL"),
        ),
    )
