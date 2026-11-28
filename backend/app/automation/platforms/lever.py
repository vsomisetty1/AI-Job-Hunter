"""Lever apply adapter.

The form lives at jobs.lever.co/<slug>/<id>/apply (jobs.eu.lever.co for EU
accounts: the job's own URL tells which). "Current location" is a text box
with a suggestion list; picking a suggestion fills a hidden field Lever uses,
so after typing the location the adapter selects the matching suggestion.
Lever has no cover-letter upload: the letter goes into "Additional information".
"""

import contextlib
from urllib.parse import quote, urlparse

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page

from app.automation.field_matcher import Plan
from app.automation.fields import FieldOutcome, FormField, normalize
from app.automation.form_engine import FilePayload, FormEngine, locator
from app.automation.platforms.base import PlatformAdapter


class LeverAdapter(PlatformAdapter):
    name = "lever"
    hosts = ("jobs.lever.co", "jobs.eu.lever.co")
    form_selectors = ("form#application-form", "form.application-form", "form")

    def application_url(self, slug: str, external_id: str, job_url: str | None) -> str:
        host = "jobs.lever.co"
        if job_url and (urlparse(job_url).hostname or "") in self.hosts:
            host = urlparse(job_url).hostname or host
        return f"https://{host}/{quote(slug, safe='')}/{quote(external_id, safe='')}/apply"

    async def fill_field(
        self,
        page: Page,
        engine: FormEngine,
        f: FormField,
        plan: Plan,
        files: dict[str, FilePayload],
    ) -> FieldOutcome:
        if f.key != "location" or plan.status != "fill":
            return await engine.fill(page, f, plan, files)
        return await self._location(page, f, plan)

    async def _location(self, page: Page, f: FormField, plan: Plan) -> FieldOutcome:
        """Type the location and pick Lever's suggestion: Lever clears the box on
        blur unless a suggestion was picked, so no blur is sent before that."""
        text = str(plan.value)
        outcome = FieldOutcome(
            key=f.key, label=f.label, kind=f.kind, required=f.required, status="filled",
            value=text, source=str(plan.source),
        )  # fmt: skip
        box = locator(page, f.handle)
        await box.fill(text)
        suggestions = page.locator(".dropdown-location:visible")
        try:
            await suggestions.first.wait_for(timeout=6000)
        except PlaywrightError:
            outcome.status = "failed"
            outcome.reason = "Lever suggested no location for this text: pick yours in the form."
            return outcome
        texts = [" ".join(t.split()) for t in await suggestions.all_inner_texts()]
        wanted = normalize(text)
        idx = next((i for i, t in enumerate(texts) if normalize(t).startswith(wanted)), 0)
        await suggestions.nth(idx).click()
        outcome.value = texts[idx]
        outcome.reason = "Picked from Lever's location suggestions."
        return outcome

    async def after_uploads(self, page: Page) -> None:
        """Lever reads an uploaded resume and fills the form from it; wait until
        that is done so the values filled next are not overwritten."""
        busy = page.get_by_text("Analyzing resume", exact=False)
        with contextlib.suppress(PlaywrightError):
            await busy.first.wait_for(state="hidden", timeout=20_000)
