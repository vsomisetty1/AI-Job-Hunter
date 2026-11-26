"""SQLAlchemy declarative base and shared column mixins.

The DDL source of truth is backend/schema.sql; these models mirror it.
"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, MetaData, func, text
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import Text


class Base(DeclarativeBase):
    # FK names match schema.sql: fk_<table>_<first column>
    metadata = MetaData(naming_convention={"fk": "fk_%(table_name)s_%(column_0_name)s"})


def text_array() -> ARRAY:
    return ARRAY(Text)


EMPTY_ARRAY = text("'{}'")
EMPTY_OBJECT = text("'{}'::jsonb")
EMPTY_LIST = text("'[]'::jsonb")


class UUIDPrimaryKeyMixin:
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )


class CreatedAtMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class TimestampMixin(CreatedAtMixin):
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
