"""Generic repository behaviour (used by every resource repository)."""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.agent_run import AgentRun
from app.repositories.base import Repository


class AgentRunRepository(Repository[AgentRun]):
    model = AgentRun


async def test_crud_pagination_and_count(db_conn):
    async with AsyncSession(bind=db_conn, join_transaction_mode="create_savepoint") as session:
        repo = AgentRunRepository(session)
        runs = [await repo.add(AgentRun(agent_name=f"a{i}")) for i in range(5)]
        assert all(r.id and r.started_at for r in runs)  # server defaults loaded

        assert await repo.count() == 5
        ordered = select(AgentRun).order_by(AgentRun.agent_name)
        page = await repo.list_page(limit=2, offset=1, query=ordered)
        assert [r.agent_name for r in page] == ["a1", "a2"]
        assert await repo.count(select(AgentRun).where(AgentRun.agent_name > "a2")) == 2

        updated = await repo.update(runs[0], {"output_summary": {"ok": True}})
        assert updated.output_summary == {"ok": True}
        with pytest.raises(AttributeError):
            await repo.update(runs[0], {"no_such_column": 1})

        await repo.delete(runs[1])
        assert await repo.get(runs[1].id) is None
        assert (await repo.get_or_404(runs[0].id)).id == runs[0].id
        with pytest.raises(NotFoundError):
            await repo.get_or_404(uuid.uuid4())
