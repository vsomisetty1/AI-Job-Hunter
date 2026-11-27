"""The universal form engine on a generic page: every way a field can be
labelled and every control type, filled and read back, plus validation."""

import pytest

from app.automation.field_matcher import Plan
from app.automation.form_engine import FormEngine

PAGE = """<!doctype html><html><body><form id="f">
  <span id="fn-l">Given name</span><input id="fn" aria-labelledby="fn-l" required>
  <input name="ln" aria-label="Family name">
  <label>E-mail address <input type="email" name="mail"></label>
  <div><p>Mobile number</p><div><input type="tel" name="tel"></div></div>
  <input name="city" placeholder="City">
  <input name="website" style="display:none">                  <!-- honeypot: hidden -->
  <input value="helper">                                       <!-- no name, no label: ignored -->
  <fieldset><legend>Preferred contact</legend>
    <label><input type="radio" name="contact" value="e"> Email</label>
    <label><input type="radio" name="contact" value="p"> Phone</label></fieldset>
  <fieldset><legend>Languages</legend>
    <label><input type="checkbox" name="lang" value="en"> English</label>
    <label><input type="checkbox" name="lang" value="es"> Spanish</label></fieldset>
  <label for="exp">Experience level</label>
  <select id="exp" required><option value="">Select...</option>
    <option>Junior</option><option>Senior</option></select>
  <div><label>Open to relocation?</label>
    <div><button type="button">Yes</button><button type="button">No</button></div></div>
  <div role="radiogroup" aria-label="Work style">
    <div role="radio" aria-checked="false" tabindex="0">Remote</div>
    <div role="radio" aria-checked="false" tabindex="0">Office</div></div>
  <label for="bio">Short bio</label><textarea id="bio"></textarea>
  <label for="cv">Resume</label><input id="cv" type="file" required>
  <label for="age">Age</label><input id="age" type="number" min="18">
  <label><input type="checkbox" name="terms" required> I agree to the terms</label>
</form>
<script>
for (const b of document.querySelectorAll('button')) b.onclick = () => {
  for (const o of b.parentElement.children) o.setAttribute('aria-pressed', 'false');
  b.setAttribute('aria-pressed', 'true'); };
for (const r of document.querySelectorAll('[role=radio]')) r.onclick = () => {
  for (const o of document.querySelectorAll('[role=radio]'))
    o.setAttribute('aria-checked', 'false');
  r.setAttribute('aria-checked', 'true'); };
</script></body></html>"""


@pytest.fixture()
async def page(browser_manager):
    context = await browser_manager.new_context()
    page = await context.new_page()
    await page.set_content(PAGE)
    yield page
    await context.close()


async def fields_by_label(engine, page):
    root = await page.query_selector("#f")
    return {f.label: f for f in await engine.extract(page, root)}, root


async def test_every_labelling_technique_and_control_is_found(page):
    engine = FormEngine()
    fields, _ = await fields_by_label(engine, page)
    kinds = {label: f.kind for label, f in fields.items()}
    assert kinds == {
        "Given name": "text",  # aria-labelledby
        "Family name": "text",  # aria-label
        "E-mail address": "email",  # wrapping <label>
        "Mobile number": "tel",  # nearby text
        "City": "text",  # placeholder only
        "Preferred contact": "radio",  # <legend>
        "Languages": "checkbox_group",
        "Experience level": "select",
        "Open to relocation?": "yes_no",  # button pair
        "Work style": "radio",  # role=radiogroup
        "Short bio": "textarea",
        "Resume": "file",
        "Age": "number",
        "I agree to the terms": "checkbox",
    }
    assert fields["Given name"].required and fields["Experience level"].required
    assert [o.label for o in fields["Experience level"].options] == ["Junior", "Senior"]
    assert [o.label for o in fields["Languages"].options] == ["English", "Spanish"]
    # The honeypot and the unnamed helper input are not fields.
    assert not any(f.key in ("website", "helper") for f in fields.values())


async def test_each_control_is_filled_and_read_back(page):
    engine = FormEngine()
    fields, root = await fields_by_label(engine, page)
    wanted = {
        "Given name": "Jordan", "Mobile number": "+1 415 555 0100", "Short bio": "Engineer.",
        "Experience level": "Senior", "Preferred contact": "Email", "Languages": ["Spanish"],
        "Open to relocation?": True, "Work style": "Remote", "Age": "30",
    }  # fmt: skip
    for label, value in wanted.items():
        outcome = await engine.fill(page, fields[label], Plan("fill", value, "user"), {})
        assert outcome.status == "filled", (label, outcome.reason)
    after, _ = await fields_by_label(engine, page)
    assert after["Given name"].value == "Jordan" and after["Experience level"].value == "Senior"
    assert after["Preferred contact"].value == "Email" and after["Languages"].value == "Spanish"
    assert after["Open to relocation?"].value == "Yes" and after["Work style"].value == "Remote"
    # An option that does not exist is reported, not forced.
    bad = await engine.fill(page, fields["Experience level"], Plan("fill", "Principal", "user"), {})
    assert bad.status == "failed" and "No option matches" in bad.reason


async def test_validation_lists_missing_and_invalid_fields(page):
    engine = FormEngine()
    fields, root = await fields_by_label(engine, page)
    await engine.fill(page, fields["Age"], Plan("fill", "12", "user"), {})  # below min=18
    result = await engine.validate(page, root, [])
    assert {m["label"] for m in result.missing} == {
        "Given name", "Experience level", "Resume", "I agree to the terms",
    }  # fmt: skip
    assert [p["label"] for p in result.problems] == ["Age"]
    assert not result.ok
