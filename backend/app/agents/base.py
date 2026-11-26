"""Base agent: shared Claude access and agent_runs bookkeeping."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.llm.client import ClaudeClient, LLMResult
from app.services.pipeline_service import AgentRunHandle, track_agent_run


class Agent:
    name: str = "agent"

    def __init__(
        self, llm: ClaudeClient, sessionmaker: async_sessionmaker[AsyncSession] | None = None
    ) -> None:
        self.llm = llm
        self.sessionmaker = sessionmaker

    @asynccontextmanager
    async def track(self, **kwargs: Any) -> AsyncIterator[AgentRunHandle]:
        async with track_agent_run(self.name, sessionmaker=self.sessionmaker, **kwargs) as run:
            run.output_summary["llm_calls"] = []
            yield run

    @staticmethod
    def record(run: AgentRunHandle, prompt: str, result: LLMResult[Any]) -> None:
        """Add one Claude call's usage to the run (cache hits cost nothing)."""
        u = result.usage
        if not result.cached:
            run.add_usage(u.input_tokens, u.output_tokens, u.cost_usd)
        run.output_summary["llm_calls"].append(
            {
                "prompt": prompt,
                "model": u.model,
                "cached": result.cached,
                "input_tokens": u.input_tokens,
                "output_tokens": u.output_tokens,
                "request_id": result.request_id,
            }
        )
