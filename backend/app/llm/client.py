"""Claude client for structured extraction and analysis.

* Structured outputs: `client.beta.messages.parse(output_format=Model)` returns a
  validated Pydantic object; no JSON scraping.
* Refusal fallback: with CLAUDE_REFUSAL_FALLBACK, a request the model declines
  is re-run server-side on a fallback model (`fallbacks="default"`).
* Retries: the SDK retries 408/409/429/5xx and connection errors with
  exponential backoff (CLAUDE_MAX_RETRIES). A response cut off by max_tokens is
  retried once with double the budget.
* Errors map to three app errors: configuration problems (bad key, billing),
  temporary failures (rate limits, outages) and permanent request errors.
  Callers degrade to deterministic results on any of them.
* Caching: identical requests are answered from Postgres (app/llm/cache.py).
* Pacing: callers may pass a `RateLimiter`; it spaces out real API calls only.
* Cost: every call returns token usage and USD cost for agent_runs.
"""

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import anthropic
from fastapi import status
from pydantic import BaseModel, ValidationError

from app.core.config import Settings
from app.core.exceptions import AppError
from app.llm.cache import LLMCache
from app.llm.pricing import cost_usd
from app.llm.prompts.base import PromptTemplate
from app.llm.rate_limit import RateLimiter
from app.utils.hashing import hash_json

logger = logging.getLogger(__name__)

FALLBACK_BETA = "server-side-fallback-2026-07-01"


class LLMError(AppError):
    status_code = status.HTTP_502_BAD_GATEWAY
    code = "llm_error"
    retryable = False


class LLMNotConfiguredError(LLMError):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = "llm_not_configured"


class LLMTemporaryError(LLMError):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = "llm_unavailable"
    retryable = True


class LLMRefusalError(LLMError):
    code = "llm_refusal"


@dataclass(frozen=True)
class LLMUsage:
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: Decimal = Decimal(0)


@dataclass(frozen=True)
class LLMResult[T: BaseModel]:
    output: T
    usage: LLMUsage
    cached: bool
    request_id: str | None = None


def _cache_key(prompt: PromptTemplate[Any], model: str, effort: str, system: str, user: str) -> str:
    return hash_json(
        {
            "prompt": prompt.name,
            "version": prompt.version,
            "model": model,
            "effort": effort,
            "schema": prompt.output_model.model_json_schema(),
            "system": system,
            "user": user,
        }
    )


class ClaudeClient:
    def __init__(
        self,
        settings: Settings,
        cache: LLMCache | None = None,
        client: Any | None = None,
    ) -> None:
        self.settings = settings
        self.cache = cache
        if client is not None:
            self._client = client
        elif settings.llm_enabled and settings.anthropic_api_key is not None:
            self._client = anthropic.AsyncAnthropic(
                api_key=settings.anthropic_api_key.get_secret_value(),
                max_retries=settings.claude_max_retries,
                timeout=settings.claude_timeout_seconds,
            )
        else:
            self._client = None

    @property
    def enabled(self) -> bool:
        return self._client is not None

    async def structured[T: BaseModel](
        self,
        prompt: PromptTemplate[T],
        *,
        model: str | None = None,
        effort: str | None = None,
        use_cache: bool = True,
        limiter: RateLimiter | None = None,
        **values: str,
    ) -> LLMResult[T]:
        """Run `prompt` and return its validated output.

        `limiter` paces real API calls only: a cache hit returns at once.
        """
        if self._client is None:
            raise LLMNotConfiguredError("Claude is not configured (set ANTHROPIC_API_KEY).")
        model = model or self.settings.claude_model_analysis
        effort = effort or self.settings.claude_effort_analysis
        system, user = prompt.render(**values)
        key = _cache_key(prompt, model, effort, system, user)

        if use_cache and self.cache is not None:
            hit = await self.cache.get(key)
            if hit is not None:
                try:
                    output = prompt.output_model.model_validate(hit)
                    logger.info("llm cache hit", extra={"prompt": prompt.name})
                    return LLMResult(output, LLMUsage(model=model), cached=True)
                except ValidationError:
                    logger.warning("discarding invalid cache entry for %s", prompt.name)

        if limiter is not None:
            await limiter.acquire()
        output, usage, request_id = await self._call(prompt, model, effort, system, user)
        if self.cache is not None:
            await self.cache.put(
                key,
                purpose=prompt.purpose,
                model=usage.model,
                response=output.model_dump(mode="json"),
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
            )
        return LLMResult(output, usage, cached=False, request_id=request_id)

    async def _call[T: BaseModel](
        self, prompt: PromptTemplate[T], model: str, effort: str, system: str, user: str
    ) -> tuple[T, LLMUsage, str | None]:
        max_tokens = prompt.max_tokens
        for attempt in (1, 2):
            kwargs: dict[str, Any] = {
                "model": model,
                "max_tokens": max_tokens,
                "system": system,
                "messages": [{"role": "user", "content": user}],
                "output_format": prompt.output_model,
                "output_config": {"effort": effort},
            }
            if self.settings.claude_refusal_fallback:
                kwargs["betas"] = [FALLBACK_BETA]
                kwargs["fallbacks"] = "default"
            response = await self._send(kwargs)
            request_id = getattr(response, "_request_id", None)
            usage = self._usage(response, model)
            logger.info(
                "claude call %s: %s in / %s out tokens, $%s",
                prompt.name,
                usage.input_tokens,
                usage.output_tokens,
                usage.cost_usd,
                extra={"prompt": prompt.name, "model": usage.model, "request_id": request_id},
            )

            if response.stop_reason == "refusal":
                category = getattr(getattr(response, "stop_details", None), "category", None)
                raise LLMRefusalError(
                    "Claude declined this request.",
                    {"category": category, "request_id": request_id},
                )
            if response.stop_reason == "max_tokens":
                if attempt == 1:
                    max_tokens *= 2
                    logger.warning("%s hit max_tokens; retrying with %s", prompt.name, max_tokens)
                    continue
                raise LLMError("Claude's answer was too long.", {"request_id": request_id})
            parsed = getattr(response, "parsed_output", None)
            if parsed is None:
                raise LLMError("Claude returned no structured output.", {"request_id": request_id})
            return parsed, usage, request_id
        raise AssertionError("unreachable")  # pragma: no cover

    async def _send(self, kwargs: dict[str, Any]) -> Any:
        if self._client is None:
            raise LLMNotConfiguredError("Claude is not configured (set ANTHROPIC_API_KEY).")
        try:
            return await self._client.beta.messages.parse(**kwargs)
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as exc:
            raise LLMNotConfiguredError("Claude rejected the API key.") from exc
        except anthropic.RateLimitError as exc:
            raise LLMTemporaryError("Claude rate limit reached; try again shortly.") from exc
        except anthropic.APIConnectionError as exc:  # includes timeouts
            raise LLMTemporaryError("Could not reach Claude.") from exc
        except anthropic.APIStatusError as exc:
            if exc.status_code == 402:
                raise LLMNotConfiguredError("Claude billing or spend limit problem.") from exc
            if exc.status_code >= 500:
                raise LLMTemporaryError("Claude is temporarily unavailable.") from exc
            logger.error("claude request rejected: %s %s", exc.status_code, exc.message)
            raise LLMError("Claude rejected the request.", {"status": exc.status_code}) from exc
        except ValidationError as exc:  # structured output failed schema validation
            raise LLMError("Claude's answer did not match the expected format.") from exc

    @staticmethod
    def _usage(response: Any, requested_model: str) -> LLMUsage:
        u = getattr(response, "usage", None)
        model = getattr(response, "model", None) or requested_model
        if u is None:
            return LLMUsage(model=model)
        tokens = {
            "input_tokens": u.input_tokens or 0,
            "output_tokens": u.output_tokens or 0,
            "cache_read_tokens": getattr(u, "cache_read_input_tokens", 0) or 0,
            "cache_write_tokens": getattr(u, "cache_creation_input_tokens", 0) or 0,
        }
        return LLMUsage(model=model, cost_usd=cost_usd(model, **tokens), **tokens)
