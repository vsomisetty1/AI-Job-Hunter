"""Playwright browser lifecycle, contexts and live review sessions.

* One Chromium process per app (started on first use, relaunched after a
  crash). Headless by default; AUTOMATION_HEADLESS=false shows the window,
  which is how a person solves a CAPTCHA or watches a run.
* One browser context per run: isolated cookies, loaded from and saved back
  to `browser_sessions` (per platform) so a site's consent banners and
  sign-ins persist between runs.
* A run that reaches review keeps its page open in the `SessionRegistry`
  until the user submits, cancels or leaves it idle for
  AUTOMATION_SESSION_IDLE_MINUTES; at most AUTOMATION_MAX_SESSIONS are open.
"""

import asyncio
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright

from app.core.config import Settings

logger = logging.getLogger(__name__)

ContextHook = Callable[[BrowserContext], Awaitable[None]]
VIEWPORT = {"width": 1280, "height": 900}


class BrowserManager:
    def __init__(self, settings: Settings, *, context_hook: ContextHook | None = None) -> None:
        self.settings = settings
        # Tests install routes here (mock ATS pages); production leaves it unset.
        self.context_hook = context_hook
        self._pw: Playwright | None = None
        self._browser: Browser | None = None
        self._lock = asyncio.Lock()
        self.launches = 0

    @property
    def alive(self) -> bool:
        return self._browser is not None and self._browser.is_connected()

    async def browser(self) -> Browser:
        async with self._lock:
            if self._browser is not None and self._browser.is_connected():
                return self._browser
            if self._browser is not None:
                logger.warning("browser disconnected; relaunching")
            if self._pw is None:
                self._pw = await async_playwright().start()
            self._browser = await self._pw.chromium.launch(
                headless=self.settings.automation_headless,
                executable_path=self.settings.automation_browser_path or None,
                slow_mo=self.settings.automation_slow_mo_ms or None,
            )
            self.launches += 1
            logger.info(
                "browser launched",
                extra={"headless": self.settings.automation_headless, "launch": self.launches},
            )
            return self._browser

    async def new_context(self, storage_state: dict[str, Any] | None = None) -> BrowserContext:
        browser = await self.browser()
        state: Any = storage_state if storage_state and storage_state.get("cookies") else None
        context = await browser.new_context(
            storage_state=state,
            viewport=VIEWPORT,  # type: ignore[arg-type]
            locale="en-US",
            accept_downloads=False,
        )
        context.set_default_timeout(self.settings.automation_action_timeout_ms)
        context.set_default_navigation_timeout(self.settings.automation_navigation_timeout_ms)
        if self.context_hook is not None:
            await self.context_hook(context)
        return context

    @staticmethod
    async def storage_state(context: BrowserContext) -> dict[str, Any]:
        """Cookies and local storage to persist (best effort)."""
        try:
            return dict(await context.storage_state())
        except Exception:
            logger.warning("could not read the browser storage state", exc_info=True)
            return {}

    async def crash(self) -> None:
        """Kill the browser process (tests: simulate a crash)."""
        if self._browser is not None:
            await self._browser.close()

    async def close(self) -> None:
        async with self._lock:
            if self._browser is not None:
                try:
                    await self._browser.close()
                except Exception:
                    logger.debug("browser already closed", exc_info=True)
                self._browser = None
            if self._pw is not None:
                await self._pw.stop()
                self._pw = None


@dataclass
class LiveSession:
    """An open form waiting for the user."""

    submission_id: uuid.UUID
    platform: str
    context: BrowserContext
    page: Page
    state: dict[str, Any] = field(default_factory=dict)  # agent bookkeeping (fields, plans)
    last_used: float = field(default_factory=time.monotonic)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def touch(self) -> None:
        self.last_used = time.monotonic()

    @property
    def usable(self) -> bool:
        return not self.page.is_closed()


class SessionRegistry:
    """Live sessions by submission, with a cap and an idle timeout."""

    def __init__(self, max_sessions: int, idle_seconds: float) -> None:
        self.max_sessions = max_sessions
        self.idle_seconds = idle_seconds
        self._sessions: dict[uuid.UUID, LiveSession] = {}
        self._slots = asyncio.Semaphore(max_sessions)
        self._held: set[uuid.UUID] = set()

    def get(self, submission_id: uuid.UUID) -> LiveSession | None:
        live = self._sessions.get(submission_id)
        if live is not None and not live.usable:
            return None
        return live

    def is_live(self, submission_id: uuid.UUID) -> bool:
        return self.get(submission_id) is not None

    async def acquire(self, submission_id: uuid.UUID) -> None:
        """Wait for a browser slot (a queued run waits here)."""
        if submission_id in self._held:
            return
        await self._slots.acquire()
        self._held.add(submission_id)

    def put(self, live: LiveSession) -> None:
        self._sessions[live.submission_id] = live

    async def release(self, submission_id: uuid.UUID, *, close: bool = True) -> None:
        live = self._sessions.pop(submission_id, None)
        if live is not None and close:
            try:
                await live.context.close()
            except Exception:
                logger.debug("context already closed", exc_info=True)
        if submission_id in self._held:
            self._held.discard(submission_id)
            self._slots.release()

    def idle(self, now: float | None = None) -> list[uuid.UUID]:
        now = time.monotonic() if now is None else now
        return [
            sid
            for sid, s in self._sessions.items()
            if not s.lock.locked() and now - s.last_used > self.idle_seconds
        ]

    @property
    def open_count(self) -> int:
        return len(self._sessions)

    async def close_all(self) -> None:
        for sid in list(self._sessions):
            await self.release(sid)
