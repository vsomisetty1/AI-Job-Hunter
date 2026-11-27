"""ORM: llm_cache_entries (Postgres-backed LLM response cache; no Redis)"""

from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class LLMCacheEntry(Base):
    __tablename__ = "llm_cache_entries"

    cache_key: Mapped[str] = mapped_column(Text, primary_key=True)
    purpose: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    response: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    hit_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("cache_key ~ '^[0-9a-f]{64}$'", name="ck_llm_cache_entries_key"),
        CheckConstraint(
            "input_tokens >= 0 AND output_tokens >= 0 AND hit_count >= 0",
            name="ck_llm_cache_entries_counts",
        ),
        Index("ix_llm_cache_entries_purpose", "purpose"),
        Index(
            "ix_llm_cache_entries_expires_at",
            "expires_at",
            postgresql_where=text("expires_at IS NOT NULL"),
        ),
    )
