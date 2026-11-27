"""Test doubles for external services (Claude)."""

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

from pydantic import BaseModel


@dataclass
class FakeResponse:
    parsed_output: Any
    stop_reason: str = "end_turn"
    model: str = "claude-opus-5-5"
    input_tokens: int = 1000
    output_tokens: int = 200
    stop_details: Any = None
    _request_id: str = "req_test"

    @property
    def usage(self) -> SimpleNamespace:
        return SimpleNamespace(
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
        )


@dataclass
class FakeAnthropic:
    """Mimics `AsyncAnthropic().beta.messages.parse` with queued responses.

    Queue items are FakeResponse objects, exceptions to raise, or callables
    `(kwargs) -> FakeResponse | BaseModel` for content-dependent answers.
    """

    responses: list[Any] = field(default_factory=list)
    calls: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.beta = SimpleNamespace(messages=SimpleNamespace(parse=self._parse))

    async def _parse(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if not self.responses:
            raise AssertionError(f"unexpected Claude call: {kwargs.get('system', '')[:60]}")
        item = self.responses.pop(0)
        if callable(item) and not isinstance(item, FakeResponse):
            item = item(kwargs)
        if isinstance(item, BaseException):
            raise item
        if isinstance(item, BaseModel):
            item = FakeResponse(parsed_output=item)
        return item


class MemoryLLMCache:
    """Dict-backed stand-in for app.llm.cache.LLMCache."""

    def __init__(self) -> None:
        self.data: dict[str, dict[str, Any]] = {}

    async def get(self, key: str) -> dict[str, Any] | None:
        return self.data.get(key)

    async def put(self, key: str, *, response: dict[str, Any], **_: Any) -> None:
        self.data[key] = response
