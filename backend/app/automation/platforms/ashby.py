"""Ashby apply adapter.

The form is a single-page app at jobs.ashbyhq.com/<slug>/<id>/application;
the slug is case-sensitive, so the job's own URL is preferred. Yes/No
questions are button pairs over hidden checkboxes (the engine treats them as
`yes_no` fields). The form has an "Autofill from resume" upload that the
engine ignores (it has no name or label): autofill would overwrite fields
with the site's own parse of the resume.
"""

from urllib.parse import quote, urlparse

from app.automation.platforms.base import PlatformAdapter


class AshbyAdapter(PlatformAdapter):
    name = "ashby"
    hosts = ("jobs.ashbyhq.com",)
    form_selectors = (
        ".ashby-application-form-container",
        "[class*=application-form]",
        "form",
        "main",
    )

    def application_url(self, slug: str, external_id: str, job_url: str | None) -> str:
        if job_url and (urlparse(job_url).hostname or "") in self.hosts:
            base = job_url.split("?")[0].rstrip("/")
            return base if base.endswith("/application") else f"{base}/application"
        slug, job = quote(slug, safe=""), quote(external_id, safe="")
        return f"https://jobs.ashbyhq.com/{slug}/{job}/application"
