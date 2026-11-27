from decimal import Decimal
from types import SimpleNamespace

import anthropic
import httpx2
import pytest

from app.core.config import Settings
from app.llm.client import (
    FALLBACK_BETA,
    ClaudeClient,
    LLMError,
    LLMNotConfiguredError,
    LLMRefusalError,
    LLMTemporaryError,
)
from app.llm.pricing import cost_usd
from app.llm.prompts import PROMPTS, SKILL_EXTRACTION
from app.schemas.candidate_profile import SkillExtractionOutput
from tests.fakes import FakeAnthropic, FakeResponse, MemoryLLMCache

OUT = SkillExtractionOutput(technical=["Python"], tools=["Docker"], domains=[], soft_skills=[])


def settings(**kw) -> Settings:
    return Settings(_env_file=None, database_url="postgresql://u:p@h:1/d", **kw)


def client(fake, cache=None, **kw) -> ClaudeClient:
    return ClaudeClient(settings(**kw), cache=cache, client=fake)


async def ask(c: ClaudeClient, **kw):
    return await c.structured(SKILL_EXTRACTION, known="none", text="Built Python APIs", **kw)


async def test_structured_call_shape_and_cost():
    fake = FakeAnthropic([FakeResponse(OUT, input_tokens=1000, output_tokens=200)])
    result = await ask(client(fake))
    assert result.output == OUT and not result.cached
    (call,) = fake.calls
    assert call["model"] == "claude-opus-5-5"
    assert call["output_format"] is SkillExtractionOutput
    assert call["output_config"] == {"effort": "low"}
    assert call["betas"] == [FALLBACK_BETA] and call["fallbacks"] == "default"
    assert "<resume>\nBuilt Python APIs\n</resume>" in call["messages"][0]["content"]
    assert "untrusted" in call["system"]
    # 1000 in @ $4/M + 200 out @ $20/M
    assert result.usage.cost_usd == Decimal("0.008000")


async def test_fallback_can_be_disabled_and_model_overridden():
    fake = FakeAnthropic([FakeResponse(OUT)])
    await ask(
        client(fake, claude_refusal_fallback=False), model="claude-haiku-5-5", effort="medium"
    )
    (call,) = fake.calls
    assert "betas" not in call and "fallbacks" not in call
    assert call["model"] == "claude-haiku-5-5" and call["output_config"] == {"effort": "medium"}


async def test_cache_hit_skips_api_and_key_tracks_input():
    cache = MemoryLLMCache()
    fake = FakeAnthropic([FakeResponse(OUT)] * 3)
    c = client(fake, cache=cache)
    first = await ask(c)
    second = await ask(c)
    assert not first.cached and second.cached and second.output == OUT
    assert len(fake.calls) == 1
    await c.structured(SKILL_EXTRACTION, known="none", text="Different text")
    assert len(fake.calls) == 2  # different input -> different key
    await ask(c, use_cache=False)
    assert len(fake.calls) == 3


async def test_refusal_raises():
    refusal = FakeResponse(
        None, stop_reason="refusal", stop_details=SimpleNamespace(category="cyber")
    )
    with pytest.raises(LLMRefusalError) as exc:
        await ask(client(FakeAnthropic([refusal])))
    assert exc.value.details["category"] == "cyber"


async def test_truncation_retried_once_with_bigger_budget():
    fake = FakeAnthropic([FakeResponse(None, stop_reason="max_tokens"), FakeResponse(OUT)])
    result = await ask(client(fake))
    assert result.output == OUT
    assert fake.calls[1]["max_tokens"] == 2 * fake.calls[0]["max_tokens"]
    fake = FakeAnthropic([FakeResponse(None, stop_reason="max_tokens")] * 2)
    with pytest.raises(LLMError, match="too long"):
        await ask(client(fake))


def _status_error(cls, code: int):
    req = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    return cls("boom", response=httpx2.Response(code, request=req), body=None)


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (lambda: _status_error(anthropic.AuthenticationError, 401), LLMNotConfiguredError),
        (lambda: _status_error(anthropic.RateLimitError, 429), LLMTemporaryError),
        (lambda: _status_error(anthropic.InternalServerError, 500), LLMTemporaryError),
        (lambda: _status_error(anthropic.BadRequestError, 400), LLMError),
        (
            lambda: anthropic.APIConnectionError(
                request=httpx2.Request("POST", "https://api.anthropic.com")
            ),
            LLMTemporaryError,
        ),
    ],
)
async def test_sdk_errors_are_mapped(exc, expected):
    with pytest.raises(expected) as info:
        await ask(client(FakeAnthropic([exc()])))
    assert type(info.value) is expected


async def test_not_configured_without_key():
    c = ClaudeClient(settings())
    assert not c.enabled
    with pytest.raises(LLMNotConfiguredError):
        await ask(c)


def test_pricing():
    assert cost_usd("claude-haiku-5-5", 1_000_000, 1_000_000) == Decimal("0.600000")
    assert cost_usd("claude-opus-5-5", 0, 0, cache_read_tokens=1_000_000) == Decimal("0.200000")
    assert cost_usd("claude-opus-5-5", 0, 0, cache_write_tokens=1_000_000) == Decimal("5.000000")
    assert cost_usd("unknown-model", 10, 10) == Decimal(0)


def test_prompt_registry_and_rendering():
    assert set(PROMPTS) == {
        "resume_parse",
        "profile_inference",
        "career_analysis",
        "skill_extraction",
        "job_scoring",
        "resume_tailor",
        "cover_letter",
        "application_answers",
    }
    for p in PROMPTS.values():
        assert p.version and p.max_tokens > 0
        p.output_model.model_json_schema()  # schema builds
    # JSON braces in values never break the template.
    _, user = PROMPTS["profile_inference"].render(facts='{"years": 5}', resume_json='{"a": {}}')
    assert '{"years": 5}' in user and '{"a": {}}' in user
