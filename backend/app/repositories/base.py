"""Generic async repository.

Repositories own queries; they never commit. The caller's unit of work (the
request's `get_db` session, or `session_scope()` in background jobs) decides
when to commit.
"""

from collections.abc import Sequence
from typing import Any, Generic, TypeVar

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.base import Base

ModelT = TypeVar("ModelT", bound=Base)


class Repository(Generic[ModelT]):
    model: type[ModelT]

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, id_: Any) -> ModelT | None:
        return await self.session.get(self.model, id_)

    async def get_or_404(self, id_: Any) -> ModelT:
        obj = await self.get(id_)
        if obj is None:
            raise NotFoundError(f"{self.model.__name__} not found", {"id": str(id_)})
        return obj

    def base_query(self) -> Select[tuple[ModelT]]:
        return select(self.model)

    async def list(
        self, *, limit: int = 50, offset: int = 0, query: Select[tuple[ModelT]] | None = None
    ) -> Sequence[ModelT]:
        stmt = (query if query is not None else self.base_query()).limit(limit).offset(offset)
        return (await self.session.scalars(stmt)).all()

    async def count(self, query: Select[tuple[ModelT]] | None = None) -> int:
        stmt = query if query is not None else self.base_query()
        total = await self.session.scalar(
            select(func.count()).select_from(stmt.order_by(None).subquery())
        )
        return int(total or 0)

    async def add(self, obj: ModelT) -> ModelT:
        self.session.add(obj)
        await self.session.flush()
        await self.session.refresh(obj)  # load server defaults (ids, timestamps)
        return obj

    async def update(self, obj: ModelT, values: dict[str, Any]) -> ModelT:
        for key, value in values.items():
            if not hasattr(obj, key):
                raise AttributeError(f"{self.model.__name__} has no attribute {key!r}")
            setattr(obj, key, value)
        await self.session.flush()
        await self.session.refresh(obj)  # pick up trigger-set updated_at
        return obj

    async def delete(self, obj: ModelT) -> None:
        await self.session.delete(obj)
        await self.session.flush()
