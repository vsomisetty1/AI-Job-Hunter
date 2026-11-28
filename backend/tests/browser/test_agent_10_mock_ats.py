"""Agent 10 end to end in real Chromium against mock Greenhouse, Lever and
Ashby forms: fill, upload, validate, wait for review, submit only on request,
and every failure path (closed job, changed form, upload error, reload,
rejection, CAPTCHA, no confirmation, browser crash)."""

import pytest

from app.automation.recovery import AtsChangedError, JobClosedError, classify
from tests.fixtures.ats import ASHBY_URL, GH_URL, LEVER_URL


def answers(report) -> dict[str, str]:
    return {a["label"]: a["value"] for a in report.answers}


def missing(report) -> set[str]:
    return {m["label"] for m in report.missing}


# =========================================================== Greenhouse
async def test_greenhouse_is_filled_uploaded_and_left_for_review(
    agent, registry, make_run, recorder, mock_ats
):
    run = make_run("greenhouse", GH_URL)
    report = await agent.prepare(run, recorder)

    assert report.resume == {
        "status": "uploaded", "file": "Jordan_Rivera_Resume.pdf", "field": "Resume/CV",
        "reason": None,
    }  # fmt: skip
    assert report.cover_letter["status"] == "uploaded"
    got = answers(report)
    assert got["First Name"] == "Jordan" and got["Last Name"] == "Rivera"
    assert got["Email"] == "jordan.rivera@example.com"
    assert got["Country"] == "United States +1"  # React-select option chosen by meaning
    assert got["Are you authorized to work lawfully in the United States?"] == "Yes"
    assert got["Will you now, or in the future, require sponsorship (e.g. H-1B visa)?"] == "No"
    assert got["Where did you hear about this job?"] == "Acme Careers Page"
    assert got["How would you describe your gender identity?"] == "(voluntary: declined)"
    # A team preference is not in any fact: left for the user, not guessed.
    assert missing(report) == {"Which team are you most interested in?"}
    assert not report.problems and not report.captcha and not report.ready
    # Stopped for review: the form is open, nothing was sent, a screenshot exists.
    assert registry.is_live(run.submission_id)
    assert mock_ats.posts == []
    assert [s[0] for s in recorder.screenshots] == ["review"]
    steps = [c[0] for c in recorder.checkpoints]
    assert steps[0] == "opening" and steps[-1] == "review" and "uploading" in steps


async def test_edit_then_submit_sends_exactly_once(agent, registry, make_run, recorder, mock_ats):
    run = make_run("greenhouse", GH_URL)
    await agent.prepare(run, recorder)
    live = registry.get(run.submission_id)
    report = await agent.apply_edit(live, run, "question_2", "Payments infrastructure", recorder)
    assert report.ready and report.missing == []
    assert mock_ats.posts == []  # editing never submits

    result = await agent.submit(live, recorder)
    assert result.outcome == "submitted"
    assert "Thank you for applying" in result.confirmation
    assert len(mock_ats.posts) == 1
    sent = mock_ats.posts[0]["data"]
    assert sent["first_name"] == "Jordan" and sent["question_2"] == "Payments infrastructure"
    assert sent["resume"] == ["Jordan_Rivera_Resume.pdf"]
    assert sent["question_4"] == "Yes" and sent["question_5"] == "No"


async def test_a_page_reload_mid_fill_is_detected_and_refilled(agent, make_run, recorder, mock_ats):
    mock_ats.set("greenhouse", "reload")  # typing LinkedIn reloads the page once
    report = await agent.prepare(make_run("greenhouse", GH_URL), recorder)
    assert any("reloaded while filling" in log[2] for log in recorder.logs)
    got = answers(report)
    assert got["First Name"] == "Jordan" and got["LinkedIn Profile"].startswith("https://")
    assert report.resume["status"] == "uploaded"
    assert missing(report) == {"Which team are you most interested in?"}


# ================================================================ Lever
async def test_lever_values_win_over_resume_parsing_and_location_is_picked(
    agent, make_run, recorder, mock_ats
):
    report = await agent.prepare(make_run("lever", LEVER_URL), recorder)
    got = answers(report)
    # Lever fills name/email from its own resume parse; ours are typed after it.
    assert got["Full name"] == "Jordan Rivera"
    assert got["Email"] == "jordan.rivera@example.com"
    assert got["Current location"] == "San Francisco, CA, United States"
    assert got["Are you legally authorized to work in the country for which you are applying?"] \
        == "Yes"  # fmt: skip
    assert got["Veteran status"] == "(voluntary: declined)"
    # No cover-letter upload on Lever: the letter goes into "Additional information".
    assert report.cover_letter == {"status": "pasted", "field": "Additional information"}
    assert got["Additional information"].startswith("Dear Acme hiring team")
    # A "needs review" package answer is never typed; consent is the user's.
    assert "Why do you want to work at Acme?" not in got
    left = {o["label"]: o["status"] for o in report.left_for_you}
    assert left["We may use AI notetakers in interviews."] == "consent"
    assert missing(report) == {"We may use AI notetakers in interviews."}
    assert report.resume["status"] == "uploaded"
    assert mock_ats.posts == []


# ================================================================ Ashby
async def test_ashby_yes_no_buttons_combobox_and_uploads(agent, make_run, recorder, mock_ats):
    report = await agent.prepare(make_run("ashby", ASHBY_URL), recorder)
    got = answers(report)
    assert got["Name"] == "Jordan Rivera" and got["Email"] == "jordan.rivera@example.com"
    # 10 years of experience: "at least 5 years building software?" -> Yes.
    assert got["Do you have at least 5 years of experience building software?"] == "Yes"
    # A skill-specific minimum with no reviewed years for that skill: not guessed.
    assert "Do you have at least 5 years of experience with Kubernetes?" not in got
    assert got["Where do you plan on working from?"] == "San Francisco, CA, United States"
    assert report.resume["status"] == "uploaded"
    assert report.cover_letter["status"] == "uploaded"
    # The "Autofill from resume" upload is ignored (it would overwrite fields).
    assert all("Autofill" not in o["label"] for o in report.left_for_you)
    assert missing(report) == {"Please elaborate on your experience building software in AWS"}
    assert mock_ats.posts == []


# ============================================================= failures
async def test_closed_job_and_changed_form_are_reported(agent, make_run, recorder, mock_ats):
    mock_ats.set("lever", "closed")
    with pytest.raises(JobClosedError):
        await agent.prepare(make_run("lever", LEVER_URL), recorder)
    mock_ats.set("lever", "changed")
    with pytest.raises(AtsChangedError) as exc:
        await agent.prepare(make_run("lever", LEVER_URL), recorder)
    assert classify(exc.value).kind == "ats_changed" and not classify(exc.value).retryable


async def test_upload_failure_is_shown_in_review(agent, make_run, recorder, mock_ats):
    mock_ats.set("greenhouse", "upload_error")
    report = await agent.prepare(make_run("greenhouse", GH_URL), recorder)
    assert report.resume["status"] == "failed"
    assert "try again" in report.resume["reason"]
    assert "Resume/CV" in missing(report)


async def test_rejected_submission_goes_back_to_review(agent, registry, make_run, recorder,
                                                       mock_ats):  # fmt: skip
    mock_ats.set("ashby", "reject")
    run = make_run("ashby", ASHBY_URL, edits={
        "q-aws": "I built services on AWS.",
    })  # fmt: skip
    report = await agent.prepare(run, recorder)
    assert report.ready
    result = await agent.submit(registry.get(run.submission_id), recorder)
    assert result.outcome == "rejected"
    assert any("problem with your submission" in p["message"] for p in result.report.problems)
    assert mock_ats.posts == []


async def test_captcha_and_silence_are_not_treated_as_success(
    agent, registry, make_run, recorder, mock_ats
):
    mock_ats.set("ashby", "captcha")
    run = make_run("ashby", ASHBY_URL, edits={"q-aws": "AWS work."})
    await agent.prepare(run, recorder)
    assert (await agent.submit(registry.get(run.submission_id), recorder)).outcome == "captcha"

    mock_ats.set("ashby", "silent")
    run = make_run("ashby", ASHBY_URL, edits={"q-aws": "AWS work."})
    await agent.prepare(run, recorder)
    assert (await agent.submit(registry.get(run.submission_id), recorder)).outcome == "unconfirmed"
    assert mock_ats.posts == []


async def test_browser_crash_is_classified_and_the_browser_relaunches(
    agent, browser_manager, registry, make_run, recorder
):
    run = make_run("greenhouse", GH_URL)
    await agent.prepare(run, recorder)
    live = registry.get(run.submission_id)
    await browser_manager.crash()
    with pytest.raises(Exception) as exc:
        await agent.submit(live, recorder)
    assert classify(exc.value).kind == "browser_crash" and classify(exc.value).retryable
    assert registry.get(run.submission_id) is None  # a closed page is not "live"
    # The next run starts a fresh browser.
    await agent.prepare(make_run("lever", LEVER_URL), recorder)
    assert browser_manager.launches == 2


async def test_cookies_are_saved_for_the_platform(agent, make_run, recorder):
    await agent.prepare(make_run("lever", LEVER_URL), recorder)
    assert recorder.states and recorder.states[0][0] == "lever"
    assert "cookies" in recorder.states[0][1]
