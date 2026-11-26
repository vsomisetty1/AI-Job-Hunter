"""ORM: browser_sessions"""

from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import EMPTY_OBJECT, Base, TimestampMixin, UUIDPrimaryKeyMixin


class BrowserSession(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "browser_sessions"

    platform: Mapped[str] = mapped_column(Text, nullable=False)
    account_label: Mapped[str] = mapped_column(Text, nullable=False, server_default="default")
    storage_state: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=EMPTY_OBJECT
    )
    is_valid: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("platform ~ '^[a-z_]+$'", name="ck_browser_sessions_platform"),
        CheckConstraint("btrim(account_label) <> ''", name="ck_browser_sessions_label"),
        CheckConstraint(
            "jsonb_typeof(storage_state) = 'object'", name="ck_browser_sessions_state_json"
        ),
        UniqueConstraint("platform", "account_label", name="uq_browser_sessions_platform_account"),
    )
