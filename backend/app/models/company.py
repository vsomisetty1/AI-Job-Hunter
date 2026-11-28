"""ORM: companies (one row per job board: source + slug)"""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Company(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "companies"

    name: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(Text, nullable=False)
    careers_url: Mapped[str | None] = mapped_column(Text)
    is_tracked: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"))
    last_crawled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_crawl_status: Mapped[str | None] = mapped_column(Text)
    last_error: Mapped[str | None] = mapped_column(Text)
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    industry: Mapped[str | None] = mapped_column(Text)  # set by the user, never inferred

    jobs = relationship("Job", back_populates="company")

    __table_args__ = (
        CheckConstraint("btrim(name) <> ''", name="ck_companies_name"),
        CheckConstraint("btrim(slug) <> ''", name="ck_companies_slug"),
        CheckConstraint("source ~ '^[a-z_]+$'", name="ck_companies_source"),
        CheckConstraint(
            "last_crawl_status IS NULL OR last_crawl_status IN ('ok', 'error', 'not_found')",
            name="ck_companies_crawl_status",
        ),
        CheckConstraint("consecutive_failures >= 0", name="ck_companies_failures"),
        CheckConstraint(
            "industry IS NULL OR (btrim(industry) <> '' AND length(industry) <= 80)",
            name="ck_companies_industry",
        ),
        UniqueConstraint("source", "slug", name="uq_companies_source_slug"),
        Index(
            "ix_companies_crawl_queue",
            text("last_crawled_at ASC NULLS FIRST"),
            postgresql_where=text("is_tracked"),
        ),
        Index("ix_companies_name_lower", text("lower(name)")),
    )
