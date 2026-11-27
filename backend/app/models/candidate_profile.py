"""ORM: candidate_profiles"""

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, Index, Numeric, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import (
    EMPTY_ARRAY,
    EMPTY_OBJECT,
    Base,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    text_array,
)


class CandidateProfile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "candidate_profiles"

    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str | None] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(Text)
    linkedin_url: Mapped[str | None] = mapped_column(Text)
    portfolio_url: Mapped[str | None] = mapped_column(Text)
    profile: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=EMPTY_OBJECT
    )
    inference: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=EMPTY_OBJECT
    )
    seniority: Mapped[str | None] = mapped_column(Text)
    experience_level: Mapped[str | None] = mapped_column(Text)
    years_experience: Mapped[Decimal | None] = mapped_column(Numeric(4, 1))
    primary_roles: Mapped[list[str]] = mapped_column(
        text_array(), nullable=False, server_default=EMPTY_ARRAY
    )
    related_roles: Mapped[list[str]] = mapped_column(
        text_array(), nullable=False, server_default=EMPTY_ARRAY
    )
    industries: Mapped[list[str]] = mapped_column(
        text_array(), nullable=False, server_default=EMPTY_ARRAY
    )
    skills: Mapped[list[str]] = mapped_column(
        text_array(), nullable=False, server_default=EMPTY_ARRAY
    )
    inference_status: Mapped[str] = mapped_column(Text, nullable=False, server_default="none")
    inference_error: Mapped[str | None] = mapped_column(Text)
    inferred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"))

    resumes = relationship("Resume", back_populates="profile", cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint("btrim(full_name) <> ''", name="ck_candidate_profiles_name"),
        CheckConstraint(
            "jsonb_typeof(profile) = 'object'", name="ck_candidate_profiles_profile_json"
        ),
        CheckConstraint(
            "jsonb_typeof(inference) = 'object'", name="ck_candidate_profiles_inference_json"
        ),
        CheckConstraint(
            "years_experience IS NULL OR (years_experience >= 0 AND years_experience <= 70)",
            name="ck_candidate_profiles_years",
        ),
        CheckConstraint(
            "email IS NULL OR position('@' in email) > 1",
            name="ck_candidate_profiles_email",
        ),
        CheckConstraint(
            "inference_status IN ('none', 'pending', 'running', 'complete', 'failed')",
            name="ck_candidate_profiles_inference_status",
        ),
        Index(
            "uq_candidate_profiles_single_active",
            text("(true)"),
            unique=True,
            postgresql_where=text("is_active"),
        ),
    )
