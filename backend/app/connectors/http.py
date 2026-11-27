"""HTTP access for job-board connectors: retries, backoff, limits.

* Retries timeouts, connection errors, 429 and 5xx with exponential backoff
  plus jitter, honouring `Retry-After` (capped).
* 404 means "this board does not exist": `BoardNotFoundError`, never retried.
* Other 4xx, invalid JSON and oversized responses: `ConnectorError`.
* Responses are streamed and refused above `max_bytes` (no unbounded memory).
* The User-Agent identifies the app generically; it carries no personal data.
"""

import asyncio
import json
import logging
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)

USER_AGENT = "AIJobHunter/0.5 (personal job search; +https://github.com/)"
_RETRY_STATUS = {429, 500, 502, 503, 504}


class ConnectorError(Exception):
    """A board could not be fetched or understood."""

    retryable = False

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class BoardNotFoundError(ConnectorError):
    """The board slug does not exist on this platform (HTTP 404)."""


class TemporaryConnectorError(ConnectorError):
    """Rate limited, timed out or server error, after all retries."""

    retryable = True


@dataclass(frozen=True)
class RetryPolicy:
    attempts: int = 4  # total tries
    base_delay: float = 1.0  # seconds; doubles each retry
    max_delay: float = 30.0
    max_retry_after: float = 60.0

    def delay(self, attempt: int, retry_after: str | None = None) -> float:
        if retry_after:
            try:
                return min(max(float(retry_after), 0.0), self.max_retry_after)
            except ValueError:
                pass  # HTTP-date form: fall back to backoff
        backoff: float = min(self.base_delay * 2.0 ** (attempt - 1), self.max_delay)
        return backoff * (0.5 + random.random() / 2)  # noqa: S311 - jitter, not crypto


class HttpFetcher:
    """Shared by all connectors (one connection pool)."""

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        *,
        retry: RetryPolicy | None = None,
        timeout: float = 30.0,
        max_bytes: int = 50 * 1024 * 1024,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._client = client or httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )
        self.retry = retry or RetryPolicy()
        self.max_bytes = max_bytes
        self._sleep = sleep

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _get_once(
        self, url: str, params: dict[str, Any] | None
    ) -> tuple[int, bytes, str | None]:
        async with self._client.stream("GET", url, params=params) as resp:
            declared = resp.headers.get("content-length")
            if declared and declared.isdigit() and int(declared) > self.max_bytes:
                raise ConnectorError(
                    f"response too large ({declared} bytes)", status=resp.status_code
                )
            chunks, size = [], 0
            async for chunk in resp.aiter_bytes():
                size += len(chunk)
                if size > self.max_bytes:
                    raise ConnectorError("response too large", status=resp.status_code)
                chunks.append(chunk)
            return resp.status_code, b"".join(chunks), resp.headers.get("retry-after")

    async def get_json(self, url: str, params: dict[str, Any] | None = None) -> Any:
        last: ConnectorError | None = None
        for attempt in range(1, self.retry.attempts + 1):
            retry_after = None
            try:
                status, body, retry_after = await self._get_once(url, params)
            except httpx.TimeoutException as exc:
                last = TemporaryConnectorError(f"timed out: {type(exc).__name__}")
            except httpx.TransportError as exc:
                last = TemporaryConnectorError(f"connection failed: {type(exc).__name__}")
            else:
                if status == 404:
                    raise BoardNotFoundError("board not found", status=404)
                if status in _RETRY_STATUS:
                    last = TemporaryConnectorError(f"HTTP {status}", status=status)
                elif status >= 400:
                    raise ConnectorError(f"HTTP {status}", status=status)
                else:
                    try:
                        return json.loads(body)
                    except ValueError as exc:
                        raise ConnectorError("response is not valid JSON", status=status) from exc
            if attempt < self.retry.attempts:
                wait = self.retry.delay(attempt, retry_after)
                logger.info("retrying %s in %.1fs (%s)", url, wait, last)
                await self._sleep(wait)
        raise last or ConnectorError("no request attempts configured")
