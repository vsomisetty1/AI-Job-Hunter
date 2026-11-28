"""Integration: application automation (approval mode) through the API, on
real Postgres, real Chromium and the mock ATS pages.

Covers the whole workflow: queue -> start -> waiting for review -> edit ->
confirmed submit, plus cancel, retry with checkpointed edits, automatic retry
of transient failures, idle timeout, startup recovery and every rule that
keeps the app from submitting without the user."""

import pytest

from tests.fixtures.ats import MockATS
from tests.fixtures.jobs import (
    add_company,
    add_job,
    add_profile,
    add_resume,
    execute,
    fetch,
    fetch_one,
    reset_settings,
    set_settings,
)
from tests.fixtures.resumes import sample_resume

API = "/api/v1/automation"


@pytest.fixture()
def mock_ats():
    return MockATS()


@pytest.fixture()
async def app(build_live_app, mock_ats):
    await reset_settings()
    yield build_live_app(
        browser_context_hook=mock_ats.hook,
        automation_submit_timeout_seconds=6,
        automation_action_timeout_ms=4000,
    )
    await reset_settings()


@pytest.fixture()
async def client(app, client_for):
    async with client_for(app) as c:
        yield c


async def approved_package(app, client, source: str = "lever") -> dict:
    # A reviewed answer, not a placeholder.
    await set_settings(work_authorization="Yes, I am authorized to work in the United States")
    profile = await add_profile()
    await add_resume(profile, sample_resume().model_dump(mode="json"))
    job = await add_job(await add_company("Acme", source=source))
    r = await client.post("/api/v1/packages", json={"job_id": str(job)})
    assert r.status_code == 202, r.text
    await app.state.task_manager.wait(r.json()["task_id"], timeout=60)
    pid = r.json()["package_id"]
    r = await client.post(f"/api/v1/packages/{pid}/approve")
    assert r.status_code == 200, r.text
    return {"package_id": pid, "job_id": str(job), "application_id": r.json()["application_id"]}


async def start(app, client, package_id: str) -> dict:
    r = await client.post(f"{API}/submissions", json={"package_id": package_id})
    assert r.status_code == 202, r.text
    await app.state.task_manager.wait(r.json()["task_id"], timeout=90)
    return (await client.get(f"{API}/submissions/{r.json()['submission_id']}")).json()


async def wait_task(app, response) -> None:
    assert response.status_code == 202, response.text
    await app.state.task_manager.wait(response.json()["task_id"], timeout=90)


# ============================================================== workflow
async def test_fill_review_edit_and_confirmed_submit(app, client, mock_ats):
    pkg = await approved_package(app, client)
    queue = (await client.get(f"{API}/queue")).json()
    assert [r["package_id"] for r in queue["ready"]] == [pkg["package_id"]]
    assert queue["ready"][0]["supported"] is True

    sub = await start(app, client, pkg["package_id"])
    sid = sub["id"]
    assert sub["status"] == "waiting_for_review" and sub["live"] is True
    assert sub["mode"] == "APPROVAL_MODE" and sub["attempts"] == 1
    assert sub["apply_url"].startswith("https://jobs.lever.co/")
    review = sub["review"]
    assert review["resume"]["status"] == "uploaded"
    assert review["cover_letter"]["status"] == "pasted"
    filled = {a["label"]: a["value"] for a in review["answers"]}
    assert filled["Full name"] == "Jordan Rivera"  # the sample resume's name, not Lever's parse
    assert [m["label"] for m in review["missing"]] == ["We may use AI notetakers in interviews."]
    assert sub["missing_count"] == 1 and sub["ready"] is False
    assert sub["screenshots"] and sub["editable_fields"]
    assert mock_ats.posts == []

    # Nothing is submitted while the form is incomplete, or without confirm=true.
    assert (await client.post(f"{API}/submissions/{sid}/submit", json={})).status_code == 422
    r = await client.post(f"{API}/submissions/{sid}/submit", json={"confirm": True})
    assert r.status_code == 409 and "not complete" in r.json()["error"]["message"]

    # The user answers the consent question in review.
    r = await client.patch(
        f"{API}/submissions/{sid}/fields",
        json={"key": "cards[c][field0]", "value": "Yes, I consent"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["ready"] is True and r.json()["edits"] == {"cards[c][field0]": "Yes, I consent"}
    assert mock_ats.posts == []

    await wait_task(app, await client.post(f"{API}/submissions/{sid}/submit",
                                           json={"confirm": True}))  # fmt: skip
    done = (await client.get(f"{API}/submissions/{sid}")).json()
    assert done["status"] == "submitted", done
    assert done["confirmed_at"] and done["submitted_at"]
    assert "Thanks for applying" in done["confirmation_text"]
    assert len(mock_ats.posts) == 1
    assert mock_ats.posts[0]["data"]["cards[c][field0]"] == "Yes"

    app_row = await fetch_one("SELECT * FROM applications WHERE id = :id",
                              id=pkg["application_id"])  # fmt: skip
    assert app_row["status"] == "submitted" and app_row["automation_state"] == "completed"
    pkg_row = await fetch_one("SELECT status FROM application_packages WHERE id = :id",
                              id=pkg["package_id"])  # fmt: skip
    assert pkg_row["status"] == "submitted"
    job = await fetch_one("SELECT status FROM jobs WHERE id = :id", id=pkg["job_id"])
    assert job["status"] == "applied"
    events = [e["event_type"] for e in await fetch(
        "SELECT event_type FROM application_events WHERE application_id = :id ORDER BY created_at",
        id=pkg["application_id"])]  # fmt: skip
    assert events == ["created", "approved", "automation_started", "needs_manual", "submitted"]

    # Evidence: screenshots and logs.
    shot = await client.get(f"{API}/submissions/{sid}/screenshots/1")
    assert shot.status_code == 200 and shot.content.startswith(b"\x89PNG")
    logs = (await client.get(f"{API}/logs", params={"submission_id": sid})).json()
    messages = [x["message"] for x in logs["items"]]
    assert "You confirmed the submission" in messages
    assert "Submitted: the site confirmed it" in messages
    # A submitted run is final.
    assert (await client.post(f"{API}/submissions/{sid}/retry")).status_code == 409
    assert (await client.post(f"{API}/submissions/{sid}/cancel")).status_code == 409
    history = (await client.get(f"{API}/submissions", params={"status": "submitted"})).json()
    assert history["total"] == 1


async def test_cancel_sends_nothing_and_returns_the_package_to_the_queue(app, client, mock_ats):
    pkg = await approved_package(app, client)
    sub = await start(app, client, pkg["package_id"])
    # One run per application at a time.
    r = await client.post(f"{API}/submissions", json={"package_id": pkg["package_id"]})
    assert r.status_code == 409
    r = await client.post(f"{API}/submissions/{sub['id']}/cancel")
    assert r.status_code == 200 and r.json()["status"] == "cancelled" and not r.json()["live"]
    assert app.state.automation.registry.open_count == 0
    assert mock_ats.posts == []
    queue = (await client.get(f"{API}/queue")).json()
    assert [x["package_id"] for x in queue["ready"]] == [pkg["package_id"]]
    app_row = await fetch_one("SELECT automation_state FROM applications WHERE id = :id",
                              id=pkg["application_id"])  # fmt: skip
    assert app_row["automation_state"] == "pending"


# ===================================================== failure recovery
async def test_a_failed_run_is_retried_with_the_users_edits(app, client, mock_ats):
    pkg = await approved_package(app, client, source="greenhouse")
    mock_ats.set("greenhouse", "changed")  # the form is missing: the layout changed
    sub = await start(app, client, pkg["package_id"])
    assert sub["status"] == "failed" and sub["error_kind"] == "ats_changed"
    assert "layout may have changed" in sub["error"] and sub["recovery_hint"]
    queue = (await client.get(f"{API}/queue")).json()
    assert [x["id"] for x in queue["needs_attention"]] == [sub["id"]] and queue["ready"] == []

    # Edits saved while no form is open are used when the form is reopened.
    await execute("UPDATE application_submissions SET status = 'waiting_for_review', "
                  "error = NULL, error_kind = NULL, failed_at = NULL WHERE id = :id",
                  id=sub["id"])  # fmt: skip
    r = await client.patch(f"{API}/submissions/{sub['id']}/fields",
                           json={"key": "question_2", "value": "Payments"})  # fmt: skip
    assert r.status_code == 200 and r.json()["live"] is False

    mock_ats.set("greenhouse", "ok")
    await wait_task(app, await client.post(f"{API}/submissions/{sub['id']}/retry"))
    again = (await client.get(f"{API}/submissions/{sub['id']}")).json()
    assert again["status"] == "waiting_for_review" and again["attempts"] == 2
    filled = {a["label"]: a["value"] for a in again["review"]["answers"]}
    assert filled["Which team are you most interested in?"] == "Payments"
    assert again["review"]["ready"] is True


async def test_transient_failures_are_retried_automatically(app, client, mock_ats):
    pkg = await approved_package(app, client)
    mock_ats.fail_next = 1  # the first page load is cut off
    sub = await start(app, client, pkg["package_id"])
    assert sub["status"] == "waiting_for_review" and sub["attempts"] == 2
    logs = (await client.get(f"{API}/logs", params={"submission_id": sub["id"]})).json()
    assert "Retrying from the last checkpoint" in [x["message"] for x in logs["items"]]


async def test_a_closed_job_fails_with_a_clear_reason(app, client, mock_ats):
    pkg = await approved_package(app, client)
    mock_ats.set("lever", "closed")
    sub = await start(app, client, pkg["package_id"])
    assert sub["status"] == "failed" and sub["error_kind"] == "job_closed"
    assert sub["attempts"] == 1  # not retried: retrying cannot help


async def test_unconfirmed_submission_fails_and_is_never_resent(app, client, mock_ats):
    pkg = await approved_package(app, client)
    mock_ats.set("lever", "silent")
    sub = await start(app, client, pkg["package_id"])
    await client.patch(f"{API}/submissions/{sub['id']}/fields",
                       json={"key": "cards[c][field0]", "value": "Yes, I consent"})  # fmt: skip
    await wait_task(app, await client.post(f"{API}/submissions/{sub['id']}/submit",
                                           json={"confirm": True}))  # fmt: skip
    done = (await client.get(f"{API}/submissions/{sub['id']}")).json()
    assert done["status"] == "failed" and done["error_kind"] == "unconfirmed"
    assert "apply twice" in done["error"] and done["confirmed_at"] is None
    assert done["attempts"] == 1


async def test_idle_forms_close_and_submitting_needs_an_open_form(app, client):
    pkg = await approved_package(app, client)
    sub = await start(app, client, pkg["package_id"])
    app.state.automation.registry.idle_seconds = 0
    assert await app.state.automation.sweep_idle() == 1
    detail = (await client.get(f"{API}/submissions/{sub['id']}")).json()
    assert detail["status"] == "waiting_for_review" and detail["live"] is False
    r = await client.post(f"{API}/submissions/{sub['id']}/submit", json={"confirm": True})
    assert r.status_code == 409 and "Retry to reopen" in r.json()["error"]["message"]


async def test_startup_marks_interrupted_runs_failed(app, client):
    pkg = await approved_package(app, client)
    sub = await start(app, client, pkg["package_id"])
    await execute("UPDATE application_submissions SET status = 'submitting', confirmed_at = now() "
                  "WHERE id = :id", id=sub["id"])  # fmt: skip
    assert await app.state.automation.recover_interrupted() == 1
    detail = (await client.get(f"{API}/submissions/{sub['id']}")).json()
    assert detail["status"] == "failed" and detail["error_kind"] == "interrupted"
    assert "check your email" in detail["error"]


# ================================================================= rules
async def test_only_approved_packages_for_posted_jobs_can_start(app, client):
    pkg = await approved_package(app, client)
    await execute("UPDATE jobs SET status = 'expired', expired_at = now() WHERE id = :id",
                  id=pkg["job_id"])  # fmt: skip
    r = await client.post(f"{API}/submissions", json={"package_id": pkg["package_id"]})
    assert r.status_code == 409 and "no longer posted" in r.json()["error"]["message"]
    await client.post(f"/api/v1/packages/{pkg['package_id']}/reject", json={"reason": "no"})
    r = await client.post(f"{API}/submissions", json={"package_id": pkg["package_id"]})
    assert r.status_code == 409 and "approved" in r.json()["error"]["message"]
    r = await client.post(f"{API}/submissions",
                          json={"package_id": "00000000-0000-0000-0000-000000000000"})  # fmt: skip
    assert r.status_code == 404


async def test_status_reports_approval_mode_only(client):
    status = (await client.get(f"{API}/status")).json()
    assert status["mode"] == "APPROVAL_MODE" and status["autonomous_available"] is False
    assert status["enabled"] is True and status["open_sessions"] == 0
