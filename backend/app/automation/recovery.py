"""Failure classification and retries for browser automation.

Every failure maps to one `error_kind` (stored on the submission) with a
message the user can act on, and a flag saying whether repeating the same
step can help. Transient failures (browser crash, timeout, network) are
retried automatically up to AUTOMATION_MAX_ATTEMPTS; the rest stop and wait
for the user. Submitting is NEVER retried automatically: a click that timed out
may still have gone through, and applying twice is worse than asking.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeout

logger = logging.getLogger(__name__)

ErrorKind = Literal[
    "browser_crash", "timeout", "network", "upload_failed", "validation_failed", "ats_changed",
    "captcha", "job_closed", "unconfirmed", "interrupted", "internal",
]  # fmt: skip
RETRYABLE: frozenset[str] = frozenset({"browser_crash", "timeout", "network"})


class AutomationError(Exception):
    kind: ErrorKind = "internal"

    def __init__(self, message: str, *, kind: ErrorKind | None = None) -> None:
        super().__init__(message)
        if kind is not None:
            self.kind = kind

    @property
    def retryable(self) -> bool:
        return self.kind in RETRYABLE


class AtsChangedError(AutomationError):
    kind: ErrorKind = "ats_changed"


class JobClosedError(AutomationError):
    kind: ErrorKind = "job_closed"


class UploadFailedError(AutomationError):
    kind: ErrorKind = "upload_failed"


class BrowserCrashError(AutomationError):
    kind: ErrorKind = "browser_crash"


@dataclass(frozen=True)
class Failure:
    kind: ErrorKind
    message: str
    retryable: bool


_HINTS: dict[str, str] = {
    "browser_crash": "The browser closed unexpectedly. Retry reopens the form and refills it.",
    "timeout": "The page took too long to respond. Retry reopens the form and refills it.",
    "network": "The job site could not be reached. Check your connection, then retry.",
    "upload_failed": "A document upload failed. Retry, or attach the file yourself.",
    "validation_failed": "The form reported problems. Fix them in the review screen.",
    "ats_changed": "The application form looks different from what this app knows. "
    "Apply on the job site directly, or retry later.",
    "captcha": "The site asked for a CAPTCHA. Run with a visible browser to solve it.",
    "job_closed": "The job is no longer accepting applications.",
    "unconfirmed": "The site did not confirm the submission. Check your email or the "
    "company's portal before retrying, so you do not apply twice.",
    "interrupted": "The app stopped during this step. Retry to start again.",
    "internal": "Something unexpected went wrong. The logs have the details.",
}


def hint(kind: str) -> str:
    return _HINTS.get(kind, _HINTS["internal"])


def classify(exc: BaseException) -> Failure:
    """Map any exception from a run to a stored failure."""
    if isinstance(exc, AutomationError):
        return Failure(exc.kind, str(exc) or hint(exc.kind), exc.retryable)
    if isinstance(exc, PlaywrightTimeout | asyncio.TimeoutError | TimeoutError):
        return Failure("timeout", f"{hint('timeout')} ({_short(exc)})", True)
    if isinstance(exc, PlaywrightError):
        text = str(exc)
        if any(s in text for s in ("has been closed", "Target closed", "crash", "disconnected")):
            return Failure("browser_crash", f"{hint('browser_crash')} ({_short(exc)})", True)
        if "net::ERR_" in text or "NS_ERROR" in text:
            return Failure("network", f"{hint('network')} ({_short(exc)})", True)
        return Failure("internal", f"Browser error: {_short(exc)}", False)
    return Failure("internal", f"{type(exc).__name__}: {_short(exc)}", False)


def _short(exc: BaseException) -> str:
    first = (str(exc).strip().splitlines() or [type(exc).__name__])[0]
    return first[:300]


async def with_retries[T](
    step: Callable[[], Awaitable[T]],
    *,
    attempts: int,
    on_retry: Callable[[int, Failure], Awaitable[None]] | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> T:
    """Run `step`; repeat it on retryable failures, up to `attempts` times."""
    for attempt in range(1, attempts + 1):
        try:
            return await step()
        except Exception as exc:
            failure = classify(exc)
            if not failure.retryable or attempt >= attempts:
                raise
            if on_retry is not None:
                await on_retry(attempt, failure)
            await sleep(min(2.0 * attempt, 6.0))
    raise AssertionError("unreachable")  # pragma: no cover
