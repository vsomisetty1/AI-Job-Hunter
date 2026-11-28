#!/usr/bin/env python3
"""Real-world validation of application automation, REVIEW MODE ONLY.

For Greenhouse, Lever and Ashby it discovers live jobs with the app's own
connectors, opens each job's real application form with Agent 10, uploads
documents and fills answers, validates, takes a screenshot, and closes the
form. NOTHING IS SUBMITTED:

* the script never calls the agent's submit step;
* a browser guard aborts any form-submitting navigation (POST document
  requests), and every non-GET request is recorded in the report;
* the applicant is a synthetic test persona with synthetic documents, never
  your resume: some sites (Greenhouse) store an attached file as soon as it is
  attached, before anything is submitted.

Usage (from the repository root, with the backend's virtualenv):

    python scripts/validate_automation.py --out validation-output/automation
    python scripts/validate_automation.py --jobs 1 --platform lever

Needs network access to the boards' APIs and application pages.
"""

import argparse
import asyncio
import io
import json
import sys
import time
import uuid
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

from reportlab.pdfgen import canvas  # noqa: E402

from app.agents.agent_2_job_discovery import fetch_board  # noqa: E402
from app.agents.agent_10_application_agent import ApplicationAgent, ApplyRun  # noqa: E402
from app.automation.browser_manager import BrowserManager, SessionRegistry  # noqa: E402
from app.automation.checkpoints import Checkpoint  # noqa: E402
from app.automation.field_matcher import AnswerFact, ApplicantFacts  # noqa: E402
from app.automation.form_engine import FilePayload  # noqa: E402
from app.automation.platforms import adapter_for  # noqa: E402
from app.automation.recovery import classify  # noqa: E402
from app.connectors.http import HttpFetcher  # noqa: E402
from app.connectors.registry import build_connectors  # noqa: E402
from app.core.config import Settings  # noqa: E402

BOARDS = {
    "greenhouse": ["duolingo", "gitlab", "dropbox", "reddit"],
    "lever": ["palantir", "spotify"],
    "ashby": ["ramp", "notion", "posthog", "linear"],
}
ENGINEERING = ("engineer", "developer", "software")

PERSONA = ApplicantFacts(
    full_name="Test Applicant",
    first_name="Test",
    last_name="Applicant",
    email="test.applicant@example.com",
    phone="+1 415 555 0100",
    location="San Francisco, CA",
    country="United States",
    linkedin="https://www.linkedin.com/in/test-applicant",
    github="https://github.com/test-applicant",
    current_company="Example Corp",
    current_title="Software Engineer",
    years_experience=6,
    school="Example State University",
    degree="B.S.",
    discipline="Computer Science",
    grad_year="2019",
    grad_month="May",
    answers=(
        AnswerFact("work_authorization", "Are you authorized to work?",
                   "Yes, I am authorized to work in the United States.", True),
        AnswerFact("sponsorship", "Will you require sponsorship?",
                   "No, I do not require visa sponsorship.", True),
        AnswerFact("why_company", "Why this company?", "Please write this yourself.", False),
    ),
    has_resume_file=True,
    has_cover_letter_file=True,
    cover_letter_text="Dear hiring team, this is a synthetic letter used to test form filling.",
)  # fmt: skip


def pdf(text: str) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(72, 720, text)
    c.save()
    return buf.getvalue()


FILES = {
    "resume": FilePayload("Test_Applicant_Resume.pdf", "application/pdf",
                          pdf("Test Applicant - synthetic resume for form testing")),
    "cover_letter": FilePayload("Test_Applicant_Cover_Letter.pdf", "application/pdf",
                                pdf("Synthetic cover letter for form testing")),
}  # fmt: skip


@dataclass
class Recorder:
    out: Path
    tag: str
    logs: list[dict[str, Any]] = field(default_factory=list)
    shots: list[str] = field(default_factory=list)

    async def log(self, level: str, step: str, message: str, **detail: Any) -> None:
        self.logs.append({"level": level, "step": step, "message": message})

    async def checkpoint(self, step: str, checkpoint: Checkpoint) -> None:
        return None

    async def screenshot(self, step: str, label: str, png: bytes) -> None:
        path = self.out / f"{self.tag}-{len(self.shots) + 1}-{step}.png"
        path.write_bytes(png)
        self.shots.append(path.name)

    async def save_browser_state(self, platform: str, state: dict[str, Any]) -> None:
        return None


class Guard:
    """Blocks form submissions; records every non-GET request."""

    def __init__(self) -> None:
        self.blocked: list[str] = []
        self.writes: list[str] = []

    async def hook(self, context: Any) -> None:
        async def handle(route: Any) -> None:
            req = route.request
            if req.method != "GET":
                self.writes.append(f"{req.method} {urlparse(req.url).hostname}{urlparse(req.url).path}")
            if req.method == "POST" and req.is_navigation_request():
                self.blocked.append(req.url)
                await route.abort()
                return
            await route.continue_()

        await context.route("**/*", handle)


async def discover(platform: str, per_platform: int) -> list[dict[str, Any]]:
    http = HttpFetcher()
    try:
        connector = build_connectors(http)[platform]
        picked: list[dict[str, Any]] = []
        for slug in BOARDS[platform]:
            result = await fetch_board(connector, slug)
            if not result.ok:
                continue
            jobs = [j for j in result.jobs if any(w in j.title.lower() for w in ENGINEERING)]
            for job in jobs[:1]:  # one job per company: more variety
                picked.append({"platform": platform, "slug": slug, "company": job.company_name,
                               "title": job.title, "external_id": job.source_job_id,
                               "job_url": job.url, "board_jobs": result.found})  # fmt: skip
            if len(picked) >= per_platform:
                break
        return picked
    finally:
        await http.aclose()


async def validate_job(job: dict[str, Any], out: Path, settings: Settings) -> dict[str, Any]:
    adapter = adapter_for(job["platform"])
    assert adapter is not None
    url = adapter.application_url(job["slug"], job["external_id"], job["job_url"])
    guard = Guard()
    browser = BrowserManager(settings, context_hook=guard.hook)
    registry = SessionRegistry(1, 600)
    agent = ApplicationAgent(settings, browser, registry)  # no database: nothing recorded
    tag = f"{job['platform']}-{job['slug']}"
    rec = Recorder(out, tag)
    run = ApplyRun(uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), job["platform"], url, PERSONA, FILES)
    started = time.perf_counter()
    entry: dict[str, Any] = {**job, "apply_url": url}
    try:
        report = await agent.prepare(run, rec)
        data = report.as_json()
        fields = [o for o in (registry.get(run.submission_id).state["outcomes"].values())]
        entry.update(
            ok=True,
            fields_detected=len(fields),
            kinds=dict(Counter(o.kind for o in fields)),
            statuses=dict(Counter(o.status for o in fields)),
            resume=data["resume"],
            cover_letter=data["cover_letter"],
            answers=[(a["label"][:80], a["value"][:60]) for a in data["answers"]],
            missing=[(m["label"][:80], m["reason"][:90]) for m in data["missing"]],
            problems=[p["message"][:140] for p in data["problems"]],
            failed=[(o.label[:80], o.reason[:120]) for o in fields if o.status == "failed"],
            captcha=data["captcha"],
            ready=data["ready"],
        )
    except Exception as exc:  # noqa: BLE001 - every failure is part of the report
        failure = classify(exc)
        entry.update(ok=False, error_kind=failure.kind, error=failure.message)
    finally:
        await registry.close_all()
        await browser.close()
    entry.update(
        seconds=round(time.perf_counter() - started, 1),
        screenshots=rec.shots,
        submitted=False,  # the submit step is never called
        blocked_submissions=guard.blocked,
        non_get_requests=sorted(set(guard.writes))[:20],
        warnings=[x["message"] for x in rec.logs if x["level"] in ("warning", "error")][:10],
    )
    return entry


def markdown(results: list[dict[str, Any]]) -> str:
    lines = ["# Application automation: real-world validation (review mode)", "",
             f"Generated {time.strftime('%Y-%m-%d %H:%M')}. Synthetic applicant; nothing submitted.", ""]  # fmt: skip
    for r in results:
        lines.append(f"## {r['platform']}: {r['title']} @ {r['company']}")
        lines.append(f"- Form: {r['apply_url']} ({r['seconds']} s)")
        if not r["ok"]:
            lines += [f"- **Failed** ({r['error_kind']}): {r['error']}", ""]
            continue
        lines.append(f"- Fields detected: {r['fields_detected']} {r['kinds']}")
        lines.append(f"- Outcomes: {r['statuses']}")
        lines.append(f"- Resume: {r['resume']}; cover letter: {r['cover_letter']}")
        lines.append(f"- Answers inserted ({len(r['answers'])}): " +
                     "; ".join(f"{a} = {v}" for a, v in r["answers"]))  # fmt: skip
        lines.append(f"- Missing ({len(r['missing'])}): " +
                     "; ".join(f"{a} ({why})" for a, why in r["missing"]))  # fmt: skip
        if r["failed"]:
            lines.append("- Fields that failed: " + "; ".join(f"{a}: {w}" for a, w in r["failed"]))
        if r["problems"]:
            lines.append("- Problems shown by the form: " + "; ".join(r["problems"]))
        lines.append(f"- CAPTCHA visible: {r['captcha']}; submitted: {r['submitted']}; "
                     f"blocked submissions: {len(r['blocked_submissions'])}")  # fmt: skip
        lines.append(f"- Non-GET requests: {', '.join(r['non_get_requests']) or 'none'}")
        lines.append("")
    return "\n".join(lines)


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", default="validation-output/automation")
    parser.add_argument("--jobs", type=int, default=2, help="jobs per platform")
    parser.add_argument("--platform", choices=sorted(BOARDS), action="append")
    parser.add_argument("--headed", action="store_true", help="show the browser")
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    settings = Settings(
        _env_file=None,
        database_url="postgresql://unused:unused@127.0.0.1:1/unused",
        automation_headless=not args.headed,
    )
    results = []
    for platform in args.platform or sorted(BOARDS):
        jobs = await discover(platform, args.jobs)
        print(f"{platform}: discovered {len(jobs)} job(s) to try")
        for job in jobs:
            entry = await validate_job(job, out, settings)
            results.append(entry)
            status = "ok" if entry["ok"] else f"FAILED ({entry['error_kind']})"
            print(f"  {job['company']}: {job['title'][:50]} -> {status}, "
                  f"{entry.get('fields_detected', 0)} fields, {len(entry.get('missing', []))} missing")  # fmt: skip
    (out / "report.json").write_text(json.dumps(results, indent=2, default=str))
    (out / "report.md").write_text(markdown(results))
    print(f"report: {out / 'report.md'}")


if __name__ == "__main__":
    asyncio.run(main())
