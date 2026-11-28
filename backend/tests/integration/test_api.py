"""Integration: the Phase 6 API (scores on jobs, scoring runs, settings) on real Postgres.

Uses the live-pool app because filtering and scoring commit in their own
sessions. Settings are reset around each test.
"""

import pytest

from app.llm.rate_limit import RateLimiter
from app.schemas.job_score import ClaudeJobScoreOutput
from tests.fixtures.jobs import (
    add_company,
    add_job,
    add_profile,
    execute,
    fetch_one,
    reset_settings,
    set_settings,
)


@pytest.fixture()
async def app(build_live_app, claude):
    await reset_settings()
    app = build_live_app(claude=claude, anthropic_api_key="sk-test", rescore_on_change=True)
    app.state.scoring.limiter = RateLimiter(60_000)
    yield app
    # Settings edits re-score in the background: let that finish before resetting.
    await app.state.task_manager.shutdown(timeout=30)
    await reset_settings()


@pytest.fixture()
async def client(app, client_for):
    async with client_for(app) as c:
        yield c


async def seeded(app) -> dict[str, str]:
    """Profile + three jobs: a strong fit, a weak fit, and one the filter drops."""
    await add_profile()
    acme = await add_company()
    ids = {
        "strong": await add_job(acme),
        "weak": await add_job(
            acme,
            title="Data Scientist",
            description="R and Tableau.",
            requirements=["PhD in statistics"],
            salary_min=None,
            salary_max=None,
        ),  # fmt: skip
        "dropped": await add_job(acme, title="PHP Developer"),
    }
    await set_settings(excluded_keywords=["PHP"])
    await app.state.pipeline.rescore()
    return {k: str(v) for k, v in ids.items()}


async def wait_for_scoring(app) -> None:
    for task in app.state.task_manager.list_tasks():
        if task.name == "job-scoring":
            info = await app.state.task_manager.wait(task.id, timeout=30)
            assert info.status == "succeeded", info.error


# -------------------------------------------------------------------- jobs
async def test_job_list_has_scores_sorting_and_filter_controls(app, client):
    ids = await seeded(app)

    r = await client.get("/api/v1/jobs", params={"sort": "score"})
    assert r.status_code == 200
    items = r.json()["items"]
    assert [j["id"] for j in items] == [ids["strong"], ids["weak"], ids["dropped"]]
    strong, weak, dropped = items
    assert strong["score"] > weak["score"] and strong["score_method"] == "rules"
    assert dropped["score"] is None and dropped["score_method"] is None
    assert dropped["status"] == "filtered"
    assert dropped["filter_reason"] == "Excluded keyword 'PHP' in the title"

    async def ids_for(**params):
        page = (await client.get("/api/v1/jobs", params=params)).json()
        return [j["id"] for j in page["items"]], page["total"]

    assert await ids_for(filter_state="passed", sort="score") == ([ids["strong"], ids["weak"]], 2)
    assert await ids_for(filter_state="rejected") == ([ids["dropped"]], 1)
    assert await ids_for(filter_state="pending") == ([], 0)
    assert await ids_for(min_score=strong["score"]) == ([ids["strong"]], 1)
    assert await ids_for(status="filtered") == ([ids["dropped"]], 1)

    bad = await client.get("/api/v1/jobs", params={"min_score": 101})
    assert bad.status_code == 422
    assert (await client.get("/api/v1/jobs", params={"filter_state": "x"})).status_code == 422


async def test_job_detail_has_filter_checks_and_score_breakdown(app, client):
    ids = await seeded(app)
    detail = (await client.get(f"/api/v1/jobs/{ids['strong']}")).json()
    assert detail["filter_result"]["passed"] is True
    assert {c["rule"] for c in detail["filter_result"]["checks"]} >= {"location", "salary"}
    (rules,) = detail["scores"]
    assert rules["scoring_method"] == "rules" and rules["is_current"] is True
    assert detail["score"] == rules["overall_score"]
    assert rules["breakdown"]["components"]["skills"]["detail"]["matched"]
    assert rules["matched_skills"] == ["Python", "PostgreSQL", "AWS"]

    dropped = (await client.get(f"/api/v1/jobs/{ids['dropped']}")).json()
    assert dropped["filter_result"]["passed"] is False and dropped["scores"] == []


async def test_claude_score_takes_over_while_current(app, client, claude):
    ids = await seeded(app)
    rules = await fetch_one(
        "SELECT * FROM job_scores WHERE job_id = :id AND scoring_method = 'rules'",
        id=ids["strong"],
    )
    await execute(
        """INSERT INTO job_scores (job_id, profile_id, scoring_method, overall_score, model,
                                   prompt_version, input_hash)
           VALUES (:job, :profile, 'claude', 42, 'claude-haiku-5-5', 'job_scoring:1', :hash)""",
        job=ids["strong"], profile=rules["profile_id"], hash=rules["input_hash"],
    )  # fmt: skip
    detail = (await client.get(f"/api/v1/jobs/{ids['strong']}")).json()
    assert (detail["score"], detail["score_method"]) == (42, "claude")
    listed = (await client.get("/api/v1/jobs", params={"sort": "score"})).json()["items"]
    strong = next(j for j in listed if j["id"] == ids["strong"])
    assert (strong["score"], strong["score_method"]) == (42, "claude")

    # Inputs change: the Claude row is kept but no longer counts.
    await execute("UPDATE job_scores SET input_hash = repeat('0', 64) "
                  "WHERE scoring_method = 'claude'")  # fmt: skip
    detail = (await client.get(f"/api/v1/jobs/{ids['strong']}")).json()
    assert detail["score_method"] == "rules"
    claude_row = next(s for s in detail["scores"] if s["scoring_method"] == "claude")
    assert claude_row["is_current"] is False


# ----------------------------------------------------------------- scoring
async def test_scoring_run_and_summary(app, client):
    await add_profile()
    acme = await add_company()
    await add_job(acme)
    await add_job(acme, title="PHP Developer")
    await set_settings(excluded_keywords=["PHP"])

    before = (await client.get("/api/v1/scoring/summary")).json()
    assert before["jobs_active"] == 2 and before["jobs_unfiltered"] == 2
    assert before["jobs_scored"] == 0 and before["last_run_at"] is None
    assert before["claude_available"] is True and before["claude_enabled"] is False
    assert before["claude_daily_limit"] == 100

    r = await client.post("/api/v1/scoring/runs")
    assert r.status_code == 202 and r.json()["detail"] == "Filtering and scoring started."
    await app.state.task_manager.wait(r.json()["task_id"], timeout=30)

    after = (await client.get("/api/v1/scoring/summary")).json()
    assert (after["jobs_unfiltered"], after["jobs_passed"], after["jobs_rejected"]) == (0, 1, 1)
    assert after["jobs_scored"] == 1 and after["last_run_status"] == "succeeded"
    assert after["task_running"] is False


async def test_settings_change_rescores_in_the_background(app, client):
    ids = await seeded(app)
    r = await client.patch("/api/v1/settings", json={"excluded_keywords": ["Tableau"]})
    assert r.status_code == 200 and r.json()["excluded_keywords"] == ["Tableau"]
    await wait_for_scoring(app)
    jobs = {j["id"]: j for j in (await client.get("/api/v1/jobs")).json()["items"]}
    assert jobs[ids["weak"]]["status"] == "filtered"
    assert jobs[ids["dropped"]]["status"] == "scored"  # PHP is allowed again

    # A field the filter and scorer do not read starts no run.
    tasks_before = len(app.state.task_manager.list_tasks())
    await client.patch("/api/v1/settings", json={"willing_to_relocate": True})
    assert len(app.state.task_manager.list_tasks()) == tasks_before


async def test_profile_edit_rescores_in_the_background(app, client):
    ids = await seeded(app)
    before = (await client.get(f"/api/v1/jobs/{ids['strong']}")).json()["score"]
    r = await client.patch("/api/v1/profile", json={"skills": ["Figma"]})
    assert r.status_code == 200
    await wait_for_scoring(app)
    after = (await client.get(f"/api/v1/jobs/{ids['strong']}")).json()["score"]
    assert after < before


async def test_claude_scoring_from_settings(app, client, claude):
    ids = await seeded(app)
    claude.responses = [
        ClaudeJobScoreOutput(
            overall_score=93, skills_score=90, seniority_score=95, interview_probability=50,
            growth_score=60, company_score=70, matched_skills=["Python"], missing_skills=[],
            strengths=["APIs"], concerns=[], rationale="Strong fit.",
        )
    ]  # fmt: skip
    r = await client.patch(
        "/api/v1/settings", json={"claude_scoring_enabled": True, "claude_scoring_min_score": 70}
    )
    assert r.json()["claude_scoring_enabled"] is True
    await wait_for_scoring(app)
    detail = (await client.get(f"/api/v1/jobs/{ids['strong']}")).json()
    assert (detail["score"], detail["score_method"]) == (93, "claude")
    assert len(claude.calls) == 1  # the weak job is below the minimum
    summary = (await client.get("/api/v1/scoring/summary")).json()
    assert summary["jobs_claude_scored"] == 1 and summary["claude_calls_today"] == 1


# ---------------------------------------------------------------- settings
@pytest.mark.parametrize(
    "body",
    [
        {"job_types": ["full_time", "gig"]},
        {"claude_scoring_min_score": 101},
        {"claude_scoring_enabled": None},
        {"remote_preference": "sometimes"},
    ],
)
async def test_settings_validation(client, body):
    r = await client.patch("/api/v1/settings", json=body)
    assert r.status_code == 422, r.text


async def test_settings_new_fields_round_trip(client):
    r = await client.patch(
        "/api/v1/settings",
        json={"job_types": ["contract", "full_time", "contract"], "requires_sponsorship": True},
    )
    assert r.status_code == 200
    body = (await client.get("/api/v1/settings")).json()
    assert body["job_types"] == ["contract", "full_time"]
    assert body["requires_sponsorship"] is True
    assert body["claude_scoring_enabled"] is False and body["claude_scoring_min_score"] == 60
