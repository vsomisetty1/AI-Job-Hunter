"""Greenhouse apply adapter.

Company boards on job-boards.greenhouse.io often redirect to the company's
own careers site (where the form sits in an iframe or is custom). The embed
URL serves the hosted application form for any board directly, so runs use
it: https://job-boards.greenhouse.io/embed/job_app?for=<slug>&token=<job id>.
Dropdowns are React-select comboboxes; the engine handles them by ARIA role.
"""

from urllib.parse import quote

from playwright.async_api import Page

from app.automation.platforms.base import CONFIRMED, PlatformAdapter


class GreenhouseAdapter(PlatformAdapter):
    name = "greenhouse"
    hosts = ("job-boards.greenhouse.io", "boards.greenhouse.io")
    form_selectors = ("form#application-form", "#application_form", "form")

    def application_url(self, slug: str, external_id: str, job_url: str | None) -> str:
        return (
            "https://job-boards.greenhouse.io/embed/job_app"
            f"?for={quote(slug, safe='')}&token={quote(external_id, safe='')}"
        )

    async def confirmation(self, page: Page) -> str | None:
        if "/confirmation" in page.url:
            text = await page.locator("body").inner_text()
            return " ".join(text.split())[:240] or "Greenhouse confirmation page"
        text = await page.locator("body").inner_text()
        match = CONFIRMED.search(text)
        return (
            " ".join(text[max(0, match.start() - 80) : match.end() + 160].split())
            if match
            else None
        )
