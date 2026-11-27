"""Integration: outcome tracking, analytics, insights and recommendations
through the API on real Postgres, from packages generated and submitted the
normal way (generate -> approve -> mark applied) and outcomes recorded by hand."""

from datetime import UTC, datetime, timedelta

import pytest

from tests.fixtures.jobs import (
    add_company,
    add_job,
    add_profile,
    add_resume,
    execute,
    fetch,
    fetch_one,
    reset_settings,
)
from tests.fixtures.resumes import sample_resume

API = "/api/v1"
DAY = timedelta(days=1)


@pytest.fixture()
async def app(build_live_app):
    await reset_settings()
    yield build_live_app()
    await reset_settings()


@pytest.fixture()
async def client(app, client_for):
    async with client_for(app) as c:
        yield c


async def applied(app, client, *, company, title="Senior Backend Engineer", source="greenhouse",
                  remote="hybrid", submit=True, days_ago=30) -> dict:  # fmt: skip
    job = await add_job(company, title=title, remote_type=remote)
    r = await client.post(f"{API}/packages", json={"job_id": str(job)})
    assert r.status_code == 202, r.text
    await app.state.task_manager.wait(r.json()["task_id"], timeout=60)
    pid = r.json()["package_id"]
    approved = (await client.post(f"{API}/packages/{pid}/approve")).json()
    if submit:
        await client.post(f"{API}/packages/{pid}/mark-submitted")
        sent = datetime.now(UTC) - days_ago * DAY
        await execute("UPDATE applications SET submitted_at = :t WHERE id = :id",
                      t=sent, id=approved["application_id"])  # fmt: skip
    return {"package_id": pid, "job_id": str(job), "application_id": approved["application_id"]}


async def record(client, app_id, stage, status="completed", days_ago=10, notes=None):
    when = (datetime.now(UTC) - days_ago * DAY).isoformat()
    r = await client.post(f"{API}/applications/{app_id}/events",
                          json={"stage": stage, "status": status, "occurred_at": when,
                                "notes": notes})  # fmt: skip
    assert r.status_code == 201, r.text
    return r.json()


async def seed_profile():
    profile = await add_profile()
    await add_resume(profile, sample_resume().model_dump(mode="json"))


# ======================================================== outcome tracking
async def test_interview_pipeline_and_outcome_timeline(app, client):
    await seed_profile()
    acme = await add_company("Acme", source="lever")
    a = await applied(app, client, company=acme)

    # Nothing can be recorded for an application that was never sent.
    draft = await applied(app, client, company=acme, title="Platform Engineer", submit=False)
    r = await client.post(f"{API}/applications/{draft['application_id']}/events",
                          json={"stage": "phone_screen",
                                "occurred_at": datetime.now(UTC).isoformat()})  # fmt: skip
    assert r.status_code == 409 and "not been submitted" in r.json()["error"]["message"]

    await record(client, a["application_id"], "recruiter_response", days_ago=25)
    detail = await record(client, a["application_id"], "phone_screen", status="scheduled",
                          days_ago=-2, notes="With Sam")  # fmt: skip
    assert detail["status"] == "interview" and detail["current_stage"] == "phone_screen"
    assert detail["next_scheduled"]["notes"] == "With Sam"
    assert detail["responded_at"] and detail["first_interview_at"]

    # Validation: endings are completed; completed events are not in the future.
    bad = await client.post(f"{API}/applications/{a['application_id']}/events",
                            json={"stage": "offer", "status": "scheduled",
                                  "occurred_at": datetime.now(UTC).isoformat()})  # fmt: skip
    assert bad.status_code == 422 and "record it as completed" in bad.json()["error"]["message"]
    later = (datetime.now(UTC) + 3 * DAY).isoformat()
    future = await client.post(f"{API}/applications/{a['application_id']}/events",
                               json={"stage": "onsite", "status": "completed",
                                     "occurred_at": later})  # fmt: skip
    assert future.status_code == 422

    # The screen happened; then an offer.
    event_id = next(e["id"] for e in detail["interview_events"] if e["stage"] == "phone_screen")
    held = (datetime.now(UTC) - 5 * DAY).isoformat()
    r = await client.patch(f"{API}/applications/{a['application_id']}/events/{event_id}",
                           json={"status": "completed", "occurred_at": held})  # fmt: skip
    assert r.status_code == 200
    offer = await record(client, a["application_id"], "offer", days_ago=1)
    assert offer["status"] == "offer" and offer["offer_at"]
    row = await fetch_one("SELECT status, offer_at FROM applications WHERE id = :id",
                          id=a["application_id"])  # fmt: skip
    assert row["status"] == "offer" and row["offer_at"] is not None

    # Deleting the offer (recorded by mistake) recomputes everything.
    offer_id = next(e["id"] for e in offer["interview_events"] if e["stage"] == "offer")
    r = await client.delete(f"{API}/applications/{a['application_id']}/events/{offer_id}")
    assert r.status_code == 204
    again = (await client.get(f"{API}/applications/{a['application_id']}")).json()
    assert again["status"] == "interview" and again["offer_at"] is None

    kinds = [t["kind"] for t in again["timeline"]]
    assert {"package_generated", "package_approved", "submitted", "recruiter_response",
            "phone_screen"} <= set(kinds)  # fmt: skip
    events = [e["event_type"] for e in await fetch(
        "SELECT event_type FROM application_events WHERE application_id = :id ORDER BY created_at",
        id=a["application_id"])]  # fmt: skip
    assert events.count("outcome_recorded") == 3 and "outcome_removed" in events
    assert "status_changed" in events

    pipeline = (await client.get(f"{API}/applications")).json()
    assert [p["application_id"] for p in pipeline] == [a["application_id"]]  # drafts excluded
    timeline = (await client.get(f"{API}/applications/timeline", params={"limit": 50})).json()
    assert timeline[0]["at"] >= timeline[-1]["at"]
    assert (await client.get(f"{API}/applications/00000000-0000-0000-0000-000000000000"))\
        .status_code == 404  # fmt: skip


async def test_withdrawal_and_industry(app, client):
    await seed_profile()
    acme = await add_company("Acme")
    a = await applied(app, client, company=acme)
    out = await record(client, a["application_id"], "withdrawal", days_ago=2)
    assert out["status"] == "withdrawn" and out["responded_at"] is None
    r = await client.patch(f"{API}/companies/{acme}", json={"industry": "  Fintech "})
    assert r.status_code == 200 and r.json()["industry"] == "Fintech"
    companies = (await client.get(f"{API}/insights/companies")).json()
    assert companies[0]["industry"] == "Fintech" and companies[0]["submitted"] == 1
    r = await client.patch(f"{API}/companies/{acme}", json={"industry": ""})
    assert r.json()["industry"] is None  # cleared


# ============================================================== analytics
async def test_analytics_insights_and_recommendations_from_real_rows(app, client):
    await seed_profile()
    gh = [await add_company(f"GH {i}", source="greenhouse") for i in range(3)]
    lv = [await add_company(f"Lever {i}", source="lever") for i in range(3)]
    apps_gh = [await applied(app, client, company=gh[i % 3]) for i in range(6)]
    apps_lv = [await applied(app, client, company=lv[i % 3], source="lever") for i in range(6)]
    for a in apps_gh[:5]:
        await record(client, a["application_id"], "recruiter_screen", days_ago=20)
    await record(client, apps_lv[0]["application_id"], "rejection", days_ago=15)
    await record(client, apps_gh[0]["application_id"], "offer", days_ago=3)

    summary = (await client.get(f"{API}/insights/summary")).json()
    ov = summary["overview"]
    assert (ov["submitted"], ov["interviewed"], ov["offered"], ov["responded"]) == (12, 5, 1, 6)
    assert ov["interview_rate"]["rate"] == round(5 / 12, 4) and ov["enough_data"] is True
    steps = {s["stage"]: s["count"] for s in summary["funnel"]}
    assert steps["generated"] == 12 and steps["submitted"] == 12 and steps["offered"] == 1
    assert summary["score_accuracy"]["scored_submitted"] == 12

    boards = {b["key"]: b for b in (await client.get(f"{API}/insights/boards")).json()}
    assert boards["greenhouse"]["interviewed"] == 5 and boards["lever"]["interviewed"] == 0
    assert boards["greenhouse"]["funnel"][0]["count"] == 6
    resumes = (await client.get(f"{API}/insights/resumes")).json()
    assert resumes["cover_letter"][0]["submitted"] == 12
    assert resumes["resume_variant"][0]["label"].endswith(" v1")

    report = (await client.get(f"{API}/insights")).json()
    assert report["status"] == "ok" and report["comparisons_tested"] > 0
    board = [i for i in report["insights"] if i["dimension"] == "platform"
             and i["outcome"] == "interviewed"]  # fmt: skip
    assert board and "5 of 6 (83%) vs 0 of 6 (0%)" in board[0]["detail"]

    recs = (await client.get(f"{API}/insights/recommendations")).json()
    keys = {r["key"] for r in recs}
    assert "platform:greenhouse:more" in keys or "platform:lever:less" in keys
    assert "data:record-outcomes" in keys  # 6 applications sent a month ago, no reply recorded
    r = await client.put(f"{API}/insights/recommendations/data:record-outcomes/state",
                         json={"state": "dismissed"})  # fmt: skip
    assert r.status_code == 200
    after = {x["key"] for x in (await client.get(f"{API}/insights/recommendations")).json()}
    assert "data:record-outcomes" not in after
    shown = (await client.get(f"{API}/insights/recommendations",
                              params={"include_dismissed": True})).json()  # fmt: skip
    assert next(x for x in shown if x["key"] == "data:record-outcomes")["state"] == "dismissed"
    await client.put(f"{API}/insights/recommendations/data:record-outcomes/state",
                     json={"state": None})  # fmt: skip
    assert "data:record-outcomes" in {
        x["key"] for x in (await client.get(f"{API}/insights/recommendations")).json()}  # fmt: skip

    # The Learning Agent stores a snapshot, and only when something changed.
    first = (await client.post(f"{API}/insights/refresh")).json()
    second = (await client.post(f"{API}/insights/refresh")).json()
    assert first["stored"] is True and second["stored"] is False and first["records"] == 12
    await record(client, apps_lv[1]["application_id"], "recruiter_response", days_ago=1)
    assert (await client.post(f"{API}/insights/refresh")).json()["stored"] is True
    history = (await client.get(f"{API}/insights/history")).json()
    assert len(history) == 2 and history[-1]["submitted"] == 12
    runs = await fetch("SELECT status FROM agent_runs WHERE agent_name = 'learning_agent'")
    assert len(runs) == 3 and all(r["status"] == "succeeded" for r in runs)


async def test_empty_history_says_so(client):
    summary = (await client.get(f"{API}/insights/summary")).json()
    assert summary["overview"]["submitted"] == 0 and summary["funnel"][0]["count"] == 0
    report = (await client.get(f"{API}/insights")).json()
    assert report["status"] == "insufficient_data" and report["insights"] == []
    recs = (await client.get(f"{API}/insights/recommendations")).json()
    assert [r["key"] for r in recs] == ["data:more-history"]
    assert (await client.put(f"{API}/insights/recommendations/BAD KEY/state",
                             json={"state": "done"})).status_code == 422  # fmt: skip
