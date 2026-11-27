"""Agent 10: application automation (approval mode).

`prepare` opens the job's application form, uploads the tailored resume and
cover letter, fills every field a fact supports (`field_matcher`), validates
the form and takes a screenshot, then STOPS: the open page waits in the
session registry for the user. `apply_edit` changes one field on that page;
`submit` presses the form's submit button and is only ever called after the
user confirmed in the review screen (the service and the database enforce
it). Autonomous submission is not implemented.

The agent has no database access of its own: progress, logs, screenshots and
the browser session go through the `Recorder` the service passes in.
"""

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from playwright.async_api import ElementHandle, Page

from app.agents.runs import AgentRunHandle, track_agent_run
from app.automation.browser_manager import BrowserManager, LiveSession, SessionRegistry
from app.automation.checkpoints import Checkpoint, form_signature
from app.automation.field_matcher import ApplicantFacts, Plan, plan_form
from app.automation.fields import FieldOutcome, FormField
from app.automation.form_engine import FilePayload, FormEngine, Validation
from app.automation.platforms import PlatformAdapter, adapter_for
from app.automation.recovery import AtsChangedError, AutomationError
from app.core.config import Settings

logger = logging.getLogger(__name__)

MAX_PASSES = 3  # answering a question can reveal follow-up questions
MAX_ROUNDS = 3  # refills after the page reloads mid-fill


class Recorder(Protocol):
    async def log(self, level: str, step: str, message: str, **detail: Any) -> None: ...
    async def checkpoint(self, step: str, checkpoint: Checkpoint) -> None: ...
    async def screenshot(self, step: str, label: str, png: bytes) -> None: ...
    async def save_browser_state(self, platform: str, state: dict[str, Any]) -> None: ...


@dataclass
class ApplyRun:
    submission_id: uuid.UUID
    application_id: uuid.UUID
    job_id: uuid.UUID
    platform: str
    url: str
    facts: ApplicantFacts
    files: dict[str, FilePayload]
    edits: dict[str, Any] = field(default_factory=dict)
    checkpoint: Checkpoint = field(default_factory=Checkpoint)
    browser_state: dict[str, Any] = field(default_factory=dict)
    attempt: int = 1


@dataclass
class ReviewReport:
    url: str
    resume: dict[str, Any]
    cover_letter: dict[str, Any]
    answers: list[dict[str, Any]]
    missing: list[dict[str, Any]]
    problems: list[dict[str, Any]]
    left_for_you: list[dict[str, Any]]
    captcha: bool
    fields_total: int
    form_changed: bool = False

    @property
    def ready(self) -> bool:
        return not self.missing and not self.problems

    def as_json(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "resume": self.resume,
            "cover_letter": self.cover_letter,
            "answers": self.answers,
            "missing": self.missing,
            "problems": self.problems,
            "left_for_you": self.left_for_you,
            "captcha": self.captcha,
            "fields_total": self.fields_total,
            "form_changed": self.form_changed,
            "ready": self.ready,
        }


@dataclass
class SubmitResult:
    outcome: Literal["submitted", "rejected", "captcha", "unconfirmed"]
    confirmation: str | None = None
    report: ReviewReport | None = None


class ApplicationAgent:
    name = "agent_10_application_agent"

    def __init__(
        self,
        settings: Settings,
        browser: BrowserManager,
        registry: SessionRegistry,
        engine: FormEngine | None = None,
        *,
        sessionmaker: Any = None,
    ) -> None:
        self.settings = settings
        self.browser = browser
        self.registry = registry
        self.engine = engine or FormEngine()
        self.sessionmaker = sessionmaker

    @asynccontextmanager
    async def _track(self, run: ApplyRun) -> AsyncIterator[AgentRunHandle]:
        """An agent_runs row per prepare (skipped without a database: browser tests)."""
        if self.sessionmaker is None:
            yield AgentRunHandle(id=uuid.uuid4(), agent_name=self.name)
            return
        async with track_agent_run(
            self.name,
            job_id=run.job_id,
            application_id=run.application_id,
            input_summary={"platform": run.platform, "url": run.url, "attempt": run.attempt},
            sessionmaker=self.sessionmaker,
        ) as tracked:
            yield tracked

    # ------------------------------------------------------------ prepare
    async def prepare(self, run: ApplyRun, rec: Recorder) -> ReviewReport:
        adapter = adapter_for(run.platform)
        if adapter is None:
            raise AtsChangedError(f"No automation for the {run.platform} platform.")
        async with self._track(run) as tracked:
            context = await self.browser.new_context(run.browser_state)
            page = await context.new_page()
            live = LiveSession(run.submission_id, run.platform, context, page)
            try:
                report = await self._prepare(run, rec, adapter, live)
            except BaseException:
                await context.close()
                raise
            tracked.output_summary.update(
                {
                    "fields": report.fields_total,
                    "answers": len(report.answers),
                    "missing": len(report.missing),
                    "problems": len(report.problems),
                    "resume": report.resume.get("status"),
                    "cover_letter": report.cover_letter.get("status"),
                }
            )
        await rec.save_browser_state(run.platform, await self.browser.storage_state(context))
        self.registry.put(live)
        return report

    async def _prepare(
        self, run: ApplyRun, rec: Recorder, adapter: PlatformAdapter, live: LiveSession
    ) -> ReviewReport:
        page = live.page
        ckpt = Checkpoint(step="opening", url=run.url, attempt=run.attempt)
        await rec.checkpoint("opening", ckpt)
        await rec.log("info", "opening", f"Opening the {adapter.name} application form",
                      url=run.url, attempt=run.attempt)  # fmt: skip
        await adapter.open(page, run.url)
        root = await self._root(page, adapter)
        fields = await self.engine.extract(page, root)
        if not fields:
            raise AtsChangedError("The application form has no fields this app can read.")
        signature = form_signature([f.key for f in fields])
        changed = bool(run.checkpoint.form_signature and run.checkpoint.form_signature != signature)
        if changed:
            await rec.log("warning", "opening", "The form differs from the last attempt; "
                          "every field is checked again.")  # fmt: skip
        await rec.log("info", "opening", f"Found {len(fields)} fields",
                      fields=[f.as_dict() for f in fields])  # fmt: skip

        # A reload or navigation while filling wipes what was typed: detect it
        # and fill again from the start (up to MAX_ROUNDS times).
        navigations = [0]

        def on_nav(frame: Any) -> None:
            if frame == page.main_frame:
                navigations[0] += 1

        page.on("framenavigated", on_nav)
        ckpt.form_signature = signature
        outcomes: dict[str, FieldOutcome] = {}
        try:
            for round_ in range(1, MAX_ROUNDS + 1):
                navigations[0] = 0
                outcomes = await self._fill_form(page, adapter, run, rec, ckpt)
                if navigations[0] == 0:
                    break
                await rec.log("warning", "filling", "The page reloaded while filling; "
                              "filling it again", round=round_)  # fmt: skip
                await adapter.wait_ready(page)
            else:
                raise AutomationError(
                    "The page kept reloading while the form was filled.", kind="ats_changed"
                )
        finally:
            page.remove_listener("framenavigated", on_nav)

        ckpt.step = "validating"
        await rec.checkpoint("validating", ckpt)
        report = await self._review(page, adapter, list(outcomes.values()), run.url, changed)
        live.state = {"outcomes": outcomes, "url": run.url, "form_changed": changed}
        ckpt.step, ckpt.fields = "review", [o.as_dict() for o in outcomes.values()]
        await rec.checkpoint("review", ckpt)
        await rec.screenshot("review", "Form filled, waiting for your review",
                             await page.screenshot(full_page=True))  # fmt: skip
        await rec.log(
            "info" if report.ready else "warning",
            "review",
            "Ready for your review" if report.ready else
            f"Waiting for you: {len(report.missing)} missing, {len(report.problems)} problems",
            missing=report.missing, problems=report.problems,
        )  # fmt: skip
        return report

    async def _fill_form(
        self,
        page: Page,
        adapter: PlatformAdapter,
        run: ApplyRun,
        rec: Recorder,
        ckpt: Checkpoint,
    ) -> dict[str, FieldOutcome]:
        """Uploads, then every other field, in passes (answers can reveal
        follow-up questions)."""
        outcomes: dict[str, FieldOutcome] = {}
        root = await self._root(page, adapter)
        fields = await self.engine.extract(page, root)
        # Uploads first: some sites parse the resume and overwrite fields with
        # their own reading of it; the values filled afterwards win.
        ckpt.step = "uploading"
        await rec.checkpoint("uploading", ckpt)
        files = [f for f in fields if f.kind == "file"]
        for f, plan in zip(files, self._plans(files, run), strict=True):
            outcomes[f.key] = await self._fill_one(page, adapter, f, plan, run, rec, "uploading")
        await adapter.after_uploads(page)
        ckpt.uploads = {
            o.detail.get("doc", o.key): {"status": o.status, "file": o.value}
            for o in outcomes.values()
        }
        ckpt.step = "filling"
        await rec.checkpoint("filling", ckpt)
        for _ in range(MAX_PASSES):
            root = await self._root(page, adapter)
            current = await self.engine.extract(page, root)
            todo = [f for f in current if f.key not in outcomes]
            if not todo:
                break
            todo.sort(key=lambda f: f.kind != "file")
            for f, plan in zip(todo, self._plans(todo, run), strict=True):
                outcomes[f.key] = await self._fill_one(page, adapter, f, plan, run, rec, "filling")
            ckpt.fields = [o.as_dict() for o in outcomes.values()]
            await rec.checkpoint("filling", ckpt)
        return outcomes

    def _plans(self, fields: list[FormField], run: ApplyRun) -> list[Plan]:
        plans = plan_form(fields, run.facts)
        for i, f in enumerate(fields):
            if f.key in run.edits and f.kind != "file":
                plans[i] = Plan("fill", run.edits[f.key], "user", "user",
                                reason="Entered by you during review.")  # fmt: skip
        return plans

    async def _fill_one(
        self,
        page: Page,
        adapter: PlatformAdapter,
        f: FormField,
        plan: Plan,
        run: ApplyRun,
        rec: Recorder,
        step: str,
    ) -> FieldOutcome:
        outcome = await adapter.fill_field(page, self.engine, f, plan, run.files)
        if plan.status == "upload":
            outcome.detail["doc"] = str(plan.value)
        level = "warning" if outcome.status == "failed" else "debug" if outcome.status in (
            "skipped", "consent") else "info"  # fmt: skip
        shown = "(hidden)" if outcome.sensitive else _clip(outcome.value)
        await rec.log(
            level, step, f"{f.label or f.key}: {outcome.status}", key=f.key, kind=f.kind,
            value=shown, source=outcome.source, reason=outcome.reason,
        )  # fmt: skip
        return outcome

    async def _root(self, page: Page, adapter: PlatformAdapter) -> ElementHandle | None:
        return await adapter.form_root(page)

    async def _review(
        self,
        page: Page,
        adapter: PlatformAdapter,
        outcomes: list[FieldOutcome],
        url: str,
        changed: bool,
    ) -> ReviewReport:
        root = await self._root(page, adapter)
        validation = await self.engine.validate(page, root, outcomes)
        captcha = await self.engine.captcha_visible(page)
        return build_report(url, outcomes, validation, captcha, changed)

    # --------------------------------------------------------- after review
    async def apply_edit(
        self, live: LiveSession, run: ApplyRun, key: str, value: Any, rec: Recorder
    ) -> ReviewReport:
        adapter = _adapter(live.platform)
        page = live.page
        root = await self._root(page, adapter)
        fields = {f.key: f for f in await self.engine.extract(page, root)}
        f = fields.get(key)
        if f is None:
            raise AtsChangedError(f"The field {key!r} is no longer on the form.")
        plan = Plan("fill", value, "user", "user", reason="Entered by you during review.")
        outcome = await self._fill_one(page, adapter, f, plan, run, rec, "review")
        outcomes: dict[str, FieldOutcome] = live.state.setdefault("outcomes", {})
        outcomes[key] = outcome
        report = await self._review(
            page, adapter, list(outcomes.values()), live.state.get("url", page.url),
            live.state.get("form_changed", False),
        )  # fmt: skip
        await rec.screenshot("review", f"After your edit of {f.label or key}",
                             await page.screenshot(full_page=True))  # fmt: skip
        live.touch()
        return report

    async def revalidate(self, live: LiveSession) -> ReviewReport:
        adapter = _adapter(live.platform)
        outcomes: dict[str, FieldOutcome] = live.state.get("outcomes", {})
        return await self._review(live.page, adapter, list(outcomes.values()),
                                  live.state.get("url", live.page.url), False)  # fmt: skip

    async def submit(self, live: LiveSession, rec: Recorder) -> SubmitResult:
        """Press submit and wait for the site's answer. Called only after the
        user confirmed (the caller checks; the database refuses otherwise)."""
        adapter = _adapter(live.platform)
        page = live.page
        root = await self._root(page, adapter)
        button = adapter.submit_button(page, root)
        if not await button.count():
            raise AtsChangedError("The form's submit button was not found.")
        await rec.screenshot(
            "submitting", "Just before submitting", await page.screenshot(full_page=True)
        )
        await rec.log("info", "submitting", "Submitting the application (confirmed by you)")
        start_url = page.url
        await button.first.click()
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.settings.automation_submit_timeout_seconds
        settled_errors = 0
        while loop.time() < deadline:
            await asyncio.sleep(0.5)
            confirmation = await adapter.confirmation(page)
            if confirmation:
                await rec.screenshot(
                    "done", "The site's confirmation", await page.screenshot(full_page=True)
                )
                return SubmitResult("submitted", confirmation)
            if await self.engine.captcha_visible(page):
                await rec.screenshot(
                    "review", "CAPTCHA shown", await page.screenshot(full_page=True)
                )
                return SubmitResult("captcha", report=await self.revalidate(live))
            if page.url == start_url:
                report = await self.revalidate(live)
                if report.problems or report.missing:
                    settled_errors += 1
                    if settled_errors >= 3:  # errors stayed for ~1.5 s: the form refused
                        await rec.screenshot("review", "The form reported problems",
                                             await page.screenshot(full_page=True))  # fmt: skip
                        return SubmitResult("rejected", report=report)
                else:
                    settled_errors = 0
        await rec.screenshot("confirming", "No confirmation from the site",
                             await page.screenshot(full_page=True))  # fmt: skip
        return SubmitResult("unconfirmed")


def _adapter(platform: str) -> PlatformAdapter:
    adapter = adapter_for(platform)
    if adapter is None:
        raise AutomationError(f"No automation for the {platform} platform.")
    return adapter


def _clip(value: str, n: int = 120) -> str:
    value = " ".join(value.split())
    return value if len(value) <= n else value[: n - 1] + "…"


def build_report(
    url: str,
    outcomes: list[FieldOutcome],
    validation: Validation,
    captcha: bool,
    changed: bool = False,
) -> ReviewReport:
    """The review screen's content, from what was filled and what the form says."""

    def doc(name: str) -> dict[str, Any]:
        o = next((o for o in outcomes if o.detail.get("doc") == name or (
            o.kind == "file" and name in o.key.lower().replace("_", " ").replace("-", " ")
            and o.status != "uploaded" and not o.detail.get("doc"))), None)  # fmt: skip
        if o is None:
            pasted = next((o for o in outcomes if name == "cover_letter" and o.kind != "file"
                           and o.status == "filled" and o.source == "package"), None)  # fmt: skip
            if pasted is not None:
                return {"status": "pasted", "field": pasted.label}
            return {"status": "not_asked"}
        return {"status": o.status, "file": o.value or None, "field": o.label,
                "reason": o.reason or None}  # fmt: skip

    answers = [
        {**o.as_dict(), "value": "(voluntary: declined)" if o.sensitive else o.value}
        for o in outcomes
        if o.kind != "file" and o.status == "filled"
    ]
    left = [
        o.as_dict() for o in outcomes if o.status in ("needs_you", "consent", "skipped", "failed")
    ]
    return ReviewReport(
        url=url,
        resume=doc("resume"),
        cover_letter=doc("cover_letter"),
        answers=answers,
        missing=validation.missing,
        problems=validation.problems,
        left_for_you=left,
        captcha=captcha,
        fields_total=len(outcomes),
        form_changed=changed,
    )
