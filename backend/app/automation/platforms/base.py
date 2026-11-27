"""Platform adapter interface (Workday-ready).

The universal form engine does the filling; an adapter only knows what is
specific to one ATS: where the application form lives, how to reveal it,
widgets that need an extra step, the submit button, and what a confirmation
or a closed job looks like. A new platform implements these hooks.
"""

import contextlib
import re
from urllib.parse import urlparse

from playwright.async_api import ElementHandle, Locator, Page
from playwright.async_api import Error as PlaywrightError

from app.automation.field_matcher import Plan
from app.automation.fields import FieldOutcome, FormField
from app.automation.form_engine import FilePayload, FormEngine
from app.automation.recovery import AtsChangedError, JobClosedError

CLOSED = re.compile(
    r"no longer (accepting applications|available|open|active)|job (has been )?(closed|filled)|"
    r"position (has been|is) (filled|closed)|page (was )?not found|"
    r"couldn.?t find (that|the) (job|page)|this job (is|has) (expired|closed)",
    re.IGNORECASE,
)
CONFIRMED = re.compile(
    r"thank(s| you) for (applying|your (application|interest))|application (has been |was )?"
    r"(received|submitted|sent)|we.?ve received your application|successfully (submitted|applied)",
    re.IGNORECASE,
)
SUBMIT = re.compile(r"^\s*submit( (your )?application)?\s*$|^\s*apply( now)?\s*$", re.IGNORECASE)
APPLY = re.compile(r"^\s*apply( (for this job|now|to this job))?\s*$", re.IGNORECASE)


class PlatformAdapter:
    name = "generic"
    hosts: tuple[str, ...] = ()
    form_selectors: tuple[str, ...] = ("form",)

    def application_url(self, slug: str, external_id: str, job_url: str | None) -> str:
        if job_url:
            return job_url
        raise AtsChangedError(f"No application URL for {self.name} job {external_id}.")

    def owns(self, url: str) -> bool:
        return (urlparse(url).hostname or "") in self.hosts

    # ------------------------------------------------------------- opening
    async def open(self, page: Page, url: str) -> None:
        response = await page.goto(url, wait_until="domcontentloaded")
        if response is not None and response.status == 404:
            raise JobClosedError("The job page no longer exists (404).")
        await self.wait_ready(page)
        if await self.form_root(page) is None:
            await self.reveal_form(page)
        if await self.form_root(page) is None:
            text = await page.locator("body").inner_text()
            if CLOSED.search(text):
                raise JobClosedError("The job is no longer accepting applications.")
            raise AtsChangedError(
                f"No application form found on the {self.name} page: the layout may have changed."
            )

    async def wait_ready(self, page: Page) -> None:
        with contextlib.suppress(PlaywrightError):
            # Long-polling pages never go idle; the form check decides.
            await page.wait_for_load_state("networkidle", timeout=10_000)

    async def reveal_form(self, page: Page) -> None:
        """Click an "Apply" button when the form is behind one."""
        button = page.get_by_role("button", name=APPLY).or_(page.get_by_role("link", name=APPLY))
        if await button.count():
            await button.first.click()
            await self.wait_ready(page)

    async def form_root(self, page: Page) -> ElementHandle | None:
        """The element holding the application form (one with a file input
        or several text inputs), or None."""
        for selector in self.form_selectors:
            for el in await page.query_selector_all(selector):
                inputs = await el.query_selector_all("input:not([type=hidden]), textarea, select")
                if len(inputs) >= 3 and await el.is_visible():
                    return el
        return None

    # -------------------------------------------------------------- filling
    async def fill_field(
        self,
        page: Page,
        engine: FormEngine,
        f: FormField,
        plan: Plan,
        files: dict[str, FilePayload],
    ) -> FieldOutcome:
        """Fill one field. Adapters override this for widgets that need an
        extra step; the default is the universal engine."""
        return await engine.fill(page, f, plan, files)

    async def after_uploads(self, page: Page) -> None:
        """Wait for anything the site does with an uploaded resume (default: nothing)."""

    # ----------------------------------------------------------- submitting
    def submit_button(self, page: Page, root: ElementHandle | None = None) -> Locator:
        return page.get_by_role("button", name=SUBMIT).or_(
            page.locator("button[type=submit], input[type=submit]")
        )

    async def confirmation(self, page: Page) -> str | None:
        """Text proving the application went through, or None."""
        text = await page.locator("body").inner_text()
        match = CONFIRMED.search(text)
        if match:
            start = max(0, match.start() - 80)
            return " ".join(text[start : match.end() + 160].split())
        return None
