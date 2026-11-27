"""Universal form engine: find fields, fill them, check the result.

Controls are found by meaning (see `dom.EXTRACT_FIELDS`) and addressed only
through the `data-ajh` handle the extraction put on them, so no platform
selector is needed to fill a form. Every write is read back: a field counts
as filled only if the page shows the value afterwards.
"""

import asyncio
import logging
import re
from dataclasses import dataclass, field, replace
from typing import Any

from playwright.async_api import ElementHandle, Locator, Page
from playwright.async_api import Error as PlaywrightError

from app.automation.dom import CAPTCHA_VISIBLE, EXTRACT_FIELDS, PAGE_ERRORS
from app.automation.field_matcher import Plan, pick_option
from app.automation.fields import (
    HANDLE_ATTR,
    TEXT_KINDS,
    FieldOutcome,
    FormField,
    clean_label,
    normalize,
)

logger = logging.getLogger(__name__)
_CRASH = re.compile(r"has been closed|Target crashed|Target closed|disconnected")


@dataclass(frozen=True)
class FilePayload:
    name: str
    mime_type: str
    data: bytes

    def as_playwright(self) -> dict[str, Any]:
        return {"name": self.name, "mimeType": self.mime_type, "buffer": self.data}


@dataclass
class Validation:
    missing: list[dict[str, Any]] = field(default_factory=list)  # required and empty
    problems: list[dict[str, Any]] = field(default_factory=list)  # errors the form shows

    @property
    def ok(self) -> bool:
        return not self.missing and not self.problems


def locator(page: Page, handle: str) -> Locator:
    return page.locator(f'[{HANDLE_ATTR}="{handle}"]')


class FormEngine:
    def __init__(self, *, option_wait_ms: int = 5000, upload_wait_ms: int = 8000) -> None:
        self.option_wait_ms = option_wait_ms
        self.upload_wait_ms = upload_wait_ms

    # ---------------------------------------------------------------- read
    async def extract(self, page: Page, root: ElementHandle | None) -> list[FormField]:
        raw: list[dict[str, Any]] = await page.evaluate(EXTRACT_FIELDS, root)
        fields = [FormField.from_dom(r) for r in raw]
        # Duplicate keys (two unnamed questions with one label) get a suffix.
        seen: dict[str, int] = {}
        out = []
        for f in fields:
            n = seen.get(f.key, 0)
            seen[f.key] = n + 1
            out.append(f if n == 0 else _with_key(f, f"{f.key}#{n + 1}"))
        return out

    async def page_errors(self, page: Page, root: ElementHandle | None) -> list[str]:
        errors: list[str] = await page.evaluate(PAGE_ERRORS, root)
        return errors

    async def captcha_visible(self, page: Page) -> bool:
        return bool(await page.evaluate(CAPTCHA_VISIBLE))

    # ---------------------------------------------------------------- write
    async def fill(
        self, page: Page, f: FormField, plan: Plan, files: dict[str, FilePayload]
    ) -> FieldOutcome:
        def out(status: str, value: str = "", reason: str = "") -> FieldOutcome:
            return FieldOutcome(
                key=f.key, label=f.label, kind=f.kind, required=f.required,
                status=status,  # type: ignore[arg-type]
                value=value, source=str(plan.source), reason=reason, sensitive=plan.sensitive,
                options=[o.label for o in f.options][:50],
            )  # fmt: skip

        if plan.status in ("needs_you", "consent", "skipped"):
            return out(plan.status, reason=plan.reason)
        try:
            if plan.status == "upload":
                payload = files.get(str(plan.value))
                if payload is None:
                    return out("needs_you", reason="No file to upload.")
                await self.upload(page, f, payload)
                return out("uploaded", payload.name, plan.reason)
            shown = await self._write(page, f, plan)
        except FillError as exc:
            return out("failed", reason=str(exc))
        except PlaywrightError as exc:
            if page.is_closed() or _CRASH.search(str(exc)):
                raise  # the browser is gone: the run's recovery handles it
            first = (str(exc).strip().splitlines() or ["browser error"])[0]
            if "Timeout" in first:
                first = (
                    "The field did not respond (it may be disabled until another answer is set)."
                )
            return out("failed", reason=first[:200])
        return out("filled", shown, plan.reason)

    async def _write(self, page: Page, f: FormField, plan: Plan) -> str:
        loc = locator(page, f.handle)
        value = plan.value
        if f.kind in TEXT_KINDS:
            text = str(value)
            await self._type(loc, text, contenteditable=f.kind == "textarea")
            got = await loc.evaluate("el => el.isContentEditable ? el.textContent : el.value")
            if normalize(str(got)) != normalize(text):
                raise FillError("The field did not keep the value typed into it.")
            return text
        if f.kind == "select":
            option = self._option(f, value, plan.concept)
            await loc.select_option(label=option)
            got = await loc.evaluate("el => el.selectedOptions[0]?.textContent || ''")
            if normalize(str(got)) != normalize(option):
                raise FillError(f"Could not select “{option}”.")
            return option
        if f.kind in ("radio", "yes_no"):
            option = self._option(f, value, plan.concept)
            handle = next(o.handle for o in f.options if o.label == option)
            await self._press(page, handle)
            return option
        if f.kind == "checkbox_group":
            wanted = value if isinstance(value, list) else [str(value)]
            chosen = []
            for w in wanted:
                option = self._option(f, w, plan.concept)
                handle = next(o.handle for o in f.options if o.label == option)
                await self._press(page, handle, check=True)
                chosen.append(option)
            return ", ".join(chosen)
        if f.kind == "checkbox":
            if value not in (True, "true", "yes", "Yes", "checked"):
                raise FillError("A checkbox is only ticked when you say so.")
            await self._press(page, f.handle, check=True)
            return "checked"
        if f.kind == "combobox":
            return await self._combobox(page, loc, value, plan)
        raise FillError(f"Unsupported field type {f.kind}.")

    @staticmethod
    def _option(f: FormField, value: Any, concept: str | None = None) -> str:
        labels = [o.label for o in f.options]
        if isinstance(value, str) and value in labels:
            return value
        idx = pick_option(concept, value if isinstance(value, bool) else str(value), labels)
        if idx is None:
            raise FillError(f"No option matches “{value}”.")
        return labels[idx]

    @staticmethod
    async def _type(loc: Locator, text: str, *, contenteditable: bool) -> None:
        editable = contenteditable and await loc.evaluate("el => el.isContentEditable")
        if editable:
            await loc.click()
            await loc.evaluate("el => { el.textContent = '' }")
            await loc.press_sequentially(text)
        else:
            await loc.fill(text)
        await loc.dispatch_event("blur")

    @staticmethod
    async def _press(page: Page, handle: str, *, check: bool = False) -> None:
        """Click a radio, checkbox or button; hidden inputs are clicked through
        their label or by script, which is what a user's click on the label does."""
        loc = locator(page, handle)
        try:
            if check or await loc.evaluate("el => el.type === 'radio'"):
                await loc.check(timeout=3000)
            else:
                await loc.click(timeout=3000)
        except PlaywrightError:  # hidden input or covered control
            await loc.evaluate(
                """el => {
                  const label = el.labels && el.labels[0];
                  (label || el).click();
                }"""
            )
        state = await loc.evaluate("el => el.tagName === 'INPUT' ? el.checked : true")
        if not state:
            raise FillError("The option did not stay selected.")

    async def _combobox(self, page: Page, loc: Locator, value: Any, plan: Plan) -> str:
        """Open, type, wait for options, pick the one that means `value`."""
        preferred = plan.options_hint
        query = "Yes" if value is True else "No" if value is False else str(value)
        if plan.concept == "location" and isinstance(value, str):
            query = value.split(",")[0]  # type the city; pick the full place from the list
        await loc.click()
        await loc.fill("")
        if preferred and not isinstance(value, bool):
            query = ""  # e.g. "decline": read the whole list rather than filter by our words
        if query:
            await loc.press_sequentially(query[:40], delay=20)
        else:
            await loc.press("ArrowDown")
        options = page.locator('[role="option"]:visible')
        try:
            await options.first.wait_for(timeout=self.option_wait_ms)
        except PlaywrightError:
            if query:  # some lists only open without a filter
                await loc.fill("")
                await loc.press("ArrowDown")
                try:
                    await options.first.wait_for(timeout=self.option_wait_ms // 2)
                except PlaywrightError as exc:
                    await loc.press("Escape")
                    raise FillError(f"No options appeared for “{query}”.") from exc
            else:
                await loc.press("Escape")
                raise FillError("No options appeared.") from None
        texts = [" ".join(t.split()) for t in await options.all_inner_texts()]
        idx = pick_option(plan.concept, value, texts, preferred=preferred)
        if idx is None and not isinstance(value, bool) and len(texts) == 1 and query:
            idx = 0  # one suggestion for exactly what we typed (a city search)
        if idx is None:
            await loc.press("Escape")
            raise FillError(f"No option matches “{query}” (options: {', '.join(texts[:6])}).")
        await options.nth(idx).click()
        await asyncio.sleep(0.15)
        return texts[idx]

    async def upload(self, page: Page, f: FormField, payload: FilePayload) -> None:
        loc = locator(page, f.handle)
        # Widgets often replace the input with a file "chip" once a file is
        # attached, so the check looks at the field's container, tagged first.
        box_id = f"box-{f.handle}"
        await loc.evaluate(_TAG_BOX, box_id)
        box = page.locator(f'[data-ajh-box="{box_id}"]')
        try:
            await loc.set_input_files(payload.as_playwright())  # type: ignore[arg-type]
        except PlaywrightError as exc:
            raise FillError(f"The upload was refused: {str(exc).splitlines()[0][:200]}") from exc
        deadline = asyncio.get_running_loop().time() + self.upload_wait_ms / 1000
        while True:
            if await box.count():
                state = await box.evaluate(_UPLOAD_STATE, payload.name)
            else:  # the widget re-rendered the whole field: look for the file's name
                chip = page.get_by_text(payload.name, exact=True)
                state = {"count": 0, "err": "", "shown": await chip.count() > 0}
            failed = re.search(r"error|fail|invalid|too large|not supported|try again",
                               state["err"], re.I)  # fmt: skip
            if state["err"] and failed:
                raise FillError(f"The site rejected the file: {state['err'][:200]}")
            if state["count"] or state["shown"]:
                return
            if asyncio.get_running_loop().time() > deadline:
                raise FillError("The file did not attach.")
            await asyncio.sleep(0.25)

    # ---------------------------------------------------------------- check
    async def validate(
        self, page: Page, root: ElementHandle | None, outcomes: list[FieldOutcome]
    ) -> Validation:
        fields = await self.extract(page, root)
        by_key = {o.key: o for o in outcomes}
        result = Validation()
        for f in fields:
            if not f.visible and f.kind != "file":
                continue
            outcome = by_key.get(f.key)
            uploaded = outcome is not None and outcome.status == "uploaded"
            if f.kind == "combobox" and not f.filled and outcome and outcome.status == "filled":
                # Custom selects show the choice in their own markup: look for it.
                shows = await locator(page, f.handle).evaluate(_SHOWS_VALUE, outcome.value)
                f = replace(f, filled=bool(shows))
            if f.kind == "file" and outcome is not None and outcome.status == "failed":
                f = replace(f, filled=False)  # the input may hold a file the site refused
            if f.required and not f.filled and not uploaded:
                reason = (outcome.reason if outcome else "") or "Required and still empty."
                status = outcome.status if outcome else "unknown"
                result.missing.append(
                    {
                        "key": f.key,
                        "label": f.label,
                        "kind": f.kind,
                        "reason": reason,
                        "status": status,
                    }  # fmt: skip
                )
            if f.invalid or f.error:
                result.problems.append(
                    {"key": f.key, "label": f.label, "message": f.error or "Invalid value."}
                )
        known = {p["message"] for p in result.problems}
        labels = {normalize(f.label) for f in fields if f.label}
        labels |= {normalize(o.label) for o in outcomes if o.label}
        for text in await self.page_errors(page, root):
            if normalize(clean_label(text)) in labels:
                continue  # a label styled as an error, not a message
            if text not in known and not any(text in k or k in text for k in known):
                result.problems.append({"key": None, "label": None, "message": text})
        return result


class FillError(Exception):
    """One field could not be filled (the run continues)."""


def _with_key(f: FormField, key: str) -> FormField:
    return replace(f, key=key)


# Tag the smallest ancestor that holds the field's label as its "box".
_TAG_BOX = """(el, id) => {
  let box = null;
  for (const sel of ['[role=group]', 'fieldset', 'li', '[class*=question]', '[class*=upload]',
                     '[class*=field]']) {
    box = el.closest(sel);
    if (box) break;
  }
  for (let i = 0; !box && i < 5; i++) {
    const up = (box || el).parentElement;
    if (!up) break;
    if (up.querySelector('label, legend, [class*=label], [id*=label]')) { box = up; break; }
    box = null; el = up;
  }
  (box || el.parentElement).setAttribute('data-ajh-box', id);
}"""
# Is the file attached? (input holds it, or the widget shows its name), or an error.
_UPLOAD_STATE = """(box, name) => {
  const input = box.querySelector('input[type=file]');
  const marks = '[role=alert],[class*=error],[class*=Error]';
  const err = [...box.querySelectorAll(marks)]
    .filter(n => getComputedStyle(n).display !== 'none')
    .map(n => n.textContent.trim()).filter(Boolean).join(' ');
  return {count: input && input.files ? input.files.length : 0,
          shown: box.textContent.includes(name), err};
}"""
# Does the combobox's container show the chosen option?
_SHOWS_VALUE = """(el, value) => {
  let box = el.parentElement;
  for (let i = 0; box && i < 3; i++, box = box.parentElement) {
    if (box.textContent.includes(value)) return true;
  }
  return false;
}"""
