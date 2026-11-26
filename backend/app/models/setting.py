"""ORM: settings (single row, id = 1)"""
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, Integer, SmallInteger, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import EMPTY_ARRAY, EMPTY_OBJECT, Base, text_array


class Setting(Base):
    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, server_default="1")
    preferred_locations: Mapped[list[str]] = mapped_column(
        text_array(), nullable=False, server_default=EMPTY_ARRAY
    )
    remote_preference: Mapped[str] = mapped_column(Text, nullable=False, server_default="any")
    job_types: Mapped[list[str]] = mapped_column(
        text_array(), nullable=False, server_default=EMPTY_ARRAY
    )
    salary_min: Mapped[int | None] = mapped_column(Integer)
    salary_target: Mapped[int | None] = mapped_column(Integer)
    salary_currency: Mapped[str] = mapped_column(Text, nullable=False, server_default="USD")
    work_authorization: Mapped[str | None] = mapped_column(Text)
    visa_status: Mapped[str | None] = mapped_column(Text)
    requires_sponsorship: Mapped[bool] = mapped_column(nullable=False, server_default=text("false"))
    excluded_companies: Mapped[list[str]] = mapped_column(
        text_array(), nullable=False, server_default=EMPTY_ARRAY
    )
    excluded_keywords: Mapped[list[str]] = mapped_column(
        text_array(), nullable=False, server_default=EMPTY_ARRAY
    )
    application_mode: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="APPROVAL_MODE"
    )
    auto_apply_threshold: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default="80"
    )
    daily_application_cap: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default="10"
    )
    discovery_enabled: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"))
    extra: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=EMPTY_OBJECT
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint("id = 1", name="ck_settings_single_row"),
        CheckConstraint(
            "remote_preference IN ('remote_only', 'hybrid', 'onsite', 'any')",
            name="ck_settings_remote",
        ),
        CheckConstraint(
            "application_mode IN ('APPROVAL_MODE', 'AUTONOMOUS_MODE')", name="ck_settings_mode"
        ),
        CheckConstraint("auto_apply_threshold BETWEEN 0 AND 100", name="ck_settings_threshold"),
        CheckConstraint("daily_application_cap BETWEEN 0 AND 200", name="ck_settings_cap"),
        CheckConstraint("salary_currency ~ '^[A-Z]{3}$'", name="ck_settings_currency"),
        CheckConstraint(
            "(salary_min IS NULL OR salary_min >= 0) AND "
            "(salary_target IS NULL OR salary_target >= 0)",
            name="ck_settings_salary",
        ),
        CheckConstraint(
            "salary_min IS NULL OR salary_target IS NULL OR salary_min <= salary_target",
            name="ck_settings_salary_order",
        ),
        CheckConstraint("jsonb_typeof(extra) = 'object'", name="ck_settings_extra_json"),
    )
