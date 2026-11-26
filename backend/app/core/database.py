"""Async SQLAlchemy engine and session factory.

The engine is created lazily from settings so importing this module never
opens a connection (tests and Alembic import the app freely).
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.core.config import Settings, get_settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def create_engine(settings: Settings) -> AsyncEngine:
    if settings.uses_transaction_pooler:
        # pgbouncer transaction mode: no prepared-statement cache, no client pool.
        return create_async_engine(
            settings.database_url,
            echo=settings.db_echo,
            poolclass=NullPool,
            connect_args={"statement_cache_size": 0, "prepared_statement_cache_size": 0},
        )
    return create_async_engine(
        settings.database_url,
        echo=settings.db_echo,
        pool_pre_ping=True,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
    )


def configure_database(settings: Settings) -> AsyncEngine:
    """Bind the module engine to these settings (called from the app lifespan)."""
    global _engine, _sessionmaker
    _engine = create_engine(settings)
    _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = create_engine(get_settings())
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _sessionmaker


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Unit of work for code outside a request (scheduler jobs, scripts)."""
    async with get_sessionmaker()() as session:
        try:
            yield session
            await session.commit()
        except BaseException:
            await session.rollback()
            raise


async def dispose_engine() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None
