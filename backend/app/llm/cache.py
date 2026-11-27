"""Postgres-backed cache of Claude responses (table llm_cache_entries).

Keyed by a hash of everything that determines the answer: prompt name and
version, model, effort, output schema and the rendered prompt text. Any
change to a prompt template (bump its version) or to the input produces a
new key, so stale answers are never served for changed inputs.

The cache uses its own short transactions so a hit or a write never depends
on (or rolls back with) the caller's unit of work.
"""

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.llm_cache_entry import LLMCacheEntry

logger = logging.getLogger(__name__)


class LLMCache:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession], ttl_days: int = 30) -> None:
        self._sessionmaker = sessionmaker
        self.ttl_days = ttl_days

    async def get(self, key: str) -> dict[str, Any] | None:
        try:
            async with self._sessionmaker() as session, session.begin():
                now = datetime.now(UTC)
                row = await session.scalar(
                    select(LLMCacheEntry).where(
                        LLMCacheEntry.cache_key == key,
                        or_(LLMCacheEntry.expires_at.is_(None), LLMCacheEntry.expires_at > now),
                    )
                )
                if row is None:
                    return None
                await session.execute(
                    update(LLMCacheEntry)
                    .where(LLMCacheEntry.cache_key == key)
                    .values(hit_count=LLMCacheEntry.hit_count + 1)
                )
                return dict(row.response)
        except Exception:
            logger.exception("llm cache read failed")
            return None

    async def put(
        self,
        key: str,
        *,
        purpose: str,
        model: str,
        response: dict[str, Any],
        input_tokens: int,
        output_tokens: int,
    ) -> None:
        expires = datetime.now(UTC) + timedelta(days=self.ttl_days) if self.ttl_days else None
        values = {
            "cache_key": key,
            "purpose": purpose,
            "model": model,
            "response": response,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "expires_at": expires,
        }
        try:
            async with self._sessionmaker() as session, session.begin():
                stmt = insert(LLMCacheEntry).values(**values)
                await session.execute(
                    stmt.on_conflict_do_update(
                        index_elements=[LLMCacheEntry.cache_key],
                        set_={k: stmt.excluded[k] for k in values if k != "cache_key"},
                    )
                )
        except Exception:
            logger.exception("llm cache write failed")
