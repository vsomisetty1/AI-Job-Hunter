"""Integration: Discovery -> Deduplication -> Filtering -> Scoring on real Postgres.

The services open their own sessions and commit, so these tests use the
live-pool app (user tables are emptied around each test; settings are reset).
Claude is the FakeAnthropic double and job boards are mocked by respx.
"""

import datetime as dt
import json
from pathlib import Path

import httpx
import pytest
import respx

from app.connectors.http import HttpFetcher, RetryPolicy
from app.llm.client import LLMRefusalError
from app.llm.rate_limit import RateLimiter
from app.schemas.job_score import ClaudeJobScoreOutput
from tests.fakes import FakeResponse
from tests.fixtures.jobs import (
    add_company,
    add_job,
    add_profile,
    execute,
    fetch,
    fetch_one,
    key,
    reset_settings,
    set_settings,
)

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "boards"
GH = "https://boards-api.greenhouse.io/v1/boards"


async def no_sleep(_seconds: float) -> None:
    return None


@pytest.fixture()
async def app(build_live_app, claude):
    await reset_settings()
    app = build_live_app(
        claude=claude,
        anthropic_api_key="sk-test",
        http=HttpFetcher(retry=RetryPolicy(attempts=1), sleep=no_sleep),
    )
    # Pacing is covered by unit tests; keep these fast.
    app.state.scoring.limiter = RateLimiter(60_000)
    yield app
    await reset_settings()


def claude_answer(overall: int = 88, **kw) -> ClaudeJobScoreOutput:
    data = {
        "overall_score": overall, "skills_score": 80, "seniority_score": 90,
        "interview_probability": 45, "growth_score": 70, "company_score": 65,
        "matched_skills": ["Python", "PostgreSQL"], "missing_skills": ["Kubernetes"],
        "strengths": ["API design"], "concerns": ["No Kubernetes"],
        "rationale": "Strong backend fit.",
    }  # fmt: skip
    return ClaudeJobScoreOutput(**(data | kw))


async def job_row(job_id):
    return await fetch_one("SELECT * FROM jobs WHERE id = :id", id=job_id)


async def scores(job_id=None):
    where = "WHERE job_id = :id" if job_id else ""
    return await fetch(
        f"SELECT * FROM job_scores {where} ORDER BY scoring_method",
        id=job_id,
    )


# ================================================================ filtering
async def test_filter_stores_decisions_and_moves_statuses(app):
    acme = await add_company()
    keep = await add_job(acme)
    php = await add_job(acme, title="Senior PHP Engineer")
    cheap = await add_job(acme, salary_min=90_000, salary_max=110_000)
    applied = await add_job(acme, title="PHP Lead", status="applied")
    expired = await add_job(acme, title="PHP Lead", status="expired")
    await set_settings(excluded_keywords=["PHP"], salary_min=150_000)

    summary = await app.state.filtering.run()
    assert summary["evaluated"] == 3 and summary["passed"] == 1 and summary["rejected"] == 2
    assert summary["updated"] == 3 and summary["rejected_by_rule"] == {"keywords": 1, "salary": 1}

    kept, dropped, low = await job_row(keep), await job_row(php), await job_row(cheap)
    assert kept["status"] == "new" and kept["filter_reason"] is None
    assert kept["filter_result"]["passed"] is True and len(kept["filter_result"]["checks"]) == 8
    assert kept["filtered_at"] is not None and len(kept["filter_hash"]) == 64
    assert dropped["status"] == "filtered"
    assert dropped["filter_reason"] == "Excluded keyword 'PHP' in the title"
    assert low["filter_reason"].startswith("Pays up to USD 110,000, below your minimum")
    # User decisions and final states are never re-filtered.
    for untouched in (applied, expired):
        row = await job_row(untouched)
        assert row["filter_result"] is None and row["status"] in ("applied", "expired")

    # Nothing changed: nothing is written.
    again = await app.state.filtering.run()
    assert again["updated"] == 0 and again["unchanged"] == 3

    # Dropping the keyword brings the job back.
    await set_settings(excluded_keywords=[])
    await app.state.filtering.run()
    assert (await job_row(php))["status"] == "new"
    assert (await job_row(php))["filter_reason"] is None


async def test_scored_job_that_fails_later_is_filtered_and_revived_job_rechecked(app):
    acme = await add_company()
    job = await add_job(acme, remote_type="onsite")
    await app.state.filtering.run()
    await execute("UPDATE jobs SET status = 'scored' WHERE id = :id", id=job)

    await set_settings(remote_preference="remote_only")
    await app.state.filtering.run()
    row = await job_row(job)
    assert row["status"] == "filtered" and "remote only" in row["filter_reason"]

    # Discovery revives jobs as 'new' without touching the filter columns: the
    # unchanged fingerprint must not leave a rejected job marked 'new'.
    await execute("UPDATE jobs SET status = 'new' WHERE id = :id", id=job)
    summary = await app.state.filtering.run()
    assert summary["updated"] == 1 and (await job_row(job))["status"] == "filtered"


# ============================================================ deduplication
async def test_cross_board_duplicates_are_linked_filtered_and_released(app):
    acme_gh, acme_lever = await add_company("Acme"), await add_company("Acme", "lever")
    fp = key("acme", "senior backend engineer", "san francisco")
    early = dt.datetime(2026, 11, 1, tzinfo=dt.UTC)
    original = await add_job(acme_gh, dedup_key=fp, first_seen_at=early)
    copy = await add_job(acme_lever, dedup_key=fp)
    same_company_twin = await add_job(acme_gh, dedup_key=fp)  # a second opening

    result = await app.state.filtering.mark_duplicates()
    assert result == {"marked": 1, "released": 0, "duplicates": 1}
    assert (await job_row(copy))["duplicate_of"] == original
    assert (await job_row(same_company_twin))["duplicate_of"] is None
    assert (await app.state.filtering.mark_duplicates())["marked"] == 0  # idempotent

    await app.state.filtering.run()
    dup = await job_row(copy)
    assert dup["status"] == "filtered" and "another board" in dup["filter_reason"]

    # The original closes: the copy (now the earliest open posting) is no
    # longer a duplicate and comes back, and the other board's opening with
    # the same fingerprint now points at it.
    await execute(
        "UPDATE jobs SET status = 'expired', expired_at = now() WHERE id = :id", id=original
    )
    changed = await app.state.filtering.mark_duplicates()
    assert changed == {"marked": 1, "released": 1, "duplicates": 1}
    assert (await job_row(copy))["duplicate_of"] is None
    assert (await job_row(same_company_twin))["duplicate_of"] == copy
    await app.state.filtering.run()
    assert (await job_row(copy))["status"] == "new"
    assert (await job_row(same_company_twin))["status"] == "filtered"


# ============================================================== rule scoring
async def test_rule_scores_are_stored_with_breakdown_and_skip_unchanged(app):
    profile = await add_profile()
    acme = await add_company()
    good = await add_job(acme)
    other = await add_job(acme, title="Data Scientist", description="R and Tableau.",
                          requirements=["PhD in statistics"], remote_type="onsite")  # fmt: skip
    filtered = await add_job(acme, title="PHP Developer")
    await set_settings(
        excluded_keywords=["PHP"], preferred_locations=["San Francisco"], salary_target=200_000
    )
    await app.state.filtering.run()

    result = await app.state.scoring.run()
    assert result["rules"] == {"evaluated": 2, "scored": 2, "unchanged": 0}
    assert result["claude"]["enabled"] is False
    assert result["claude"]["reason"] == "disabled in settings"

    (row,) = await scores(good)
    assert row["scoring_method"] == "rules" and row["profile_id"] == profile
    assert row["model"] is None and row["prompt_version"] is None
    assert row["input_tokens"] == row["output_tokens"] == 0
    assert row["interview_probability"] is None and row["growth_score"] is None
    # 3 of 3 skills: near the top, but shrunk slightly for the small sample.
    assert 90 <= row["skills_score"] < 100 and row["relevance_score"] == 100
    assert row["salary_score"] == 100 and row["location_score"] == 100
    assert row["matched_skills"] == ["Python", "PostgreSQL", "AWS"]
    assert set(row["breakdown"]["components"]) == {
        "skills", "relevance", "seniority", "location", "salary",
    }  # fmt: skip
    assert row["rationale"].startswith("Skills: 3 of 3 skills match")
    (weak,) = await scores(other)
    assert weak["overall_score"] < row["overall_score"] - 30
    assert await scores(filtered) == []
    assert (await job_row(good))["status"] == "scored"
    assert (await job_row(filtered))["status"] == "filtered"

    again = await app.state.scoring.run()
    assert again["rules"] == {"evaluated": 2, "scored": 0, "unchanged": 2}

    # A profile change re-scores in place (one row per job + profile + method).
    await execute("UPDATE candidate_profiles SET skills = ARRAY['Rust'] WHERE id = :id", id=profile)
    third = await app.state.scoring.run()
    assert third["rules"]["scored"] == 2
    (updated,) = await scores(good)
    assert updated["id"] == row["id"] and updated["skills_score"] < row["skills_score"]
    assert updated["updated_at"] > row["updated_at"]


async def test_scoring_without_a_profile_is_skipped(app):
    await add_job(await add_company())
    await app.state.filtering.run()
    assert await app.state.scoring.run() == {"skipped": True, "reason": "no_profile"}
    assert await scores() == []


# ================================================================== Claude
async def _claude_ready(app, **settings):
    await add_profile()
    acme = await add_company()
    jobs = [await add_job(acme, title=t) for t in ("Backend Engineer", "Software Engineer")]
    jobs.append(
        await add_job(
            acme,
            title="Marketing Analyst",
            description="Campaigns and SEO.",
            requirements=["Excel"],
            salary_min=None,
            salary_max=None,
        )  # fmt: skip
    )
    await set_settings(claude_scoring_enabled=True, **settings)
    await app.state.filtering.run()
    return jobs


async def test_claude_scores_the_shortlist_and_records_usage(app, claude):
    best, second, low = await _claude_ready(app, claude_scoring_min_score=70)
    claude.responses = [claude_answer(91), claude_answer(77, interview_probability=150)]

    summary = await app.state.pipeline.rescore()
    assert summary["pipeline_ok"] is True, summary
    stage = summary["pipeline"][-1]
    assert stage["stage"] == "agent_5_job_scoring"

    rows = {r["job_id"]: r for r in await scores() if r["scoring_method"] == "claude"}
    assert set(rows) == {best, second}  # the analyst job is below the minimum
    # The two shortlisted jobs may tie on rule score, so match answers by value.
    top = next(r for r in rows.values() if r["overall_score"] == 91)
    other = next(r for r in rows.values() if r["overall_score"] == 77)
    assert top["interview_probability"] == 45
    assert other["interview_probability"] == 100  # clamped
    assert top["model"] == "claude-opus-5-5" and top["prompt_version"] == "job_scoring:1"
    assert top["input_tokens"] == 1000 and top["output_tokens"] == 200
    assert top["breakdown"]["strengths"] == ["API design"]
    rules = next(r for r in await scores(top["job_id"]) if r["scoring_method"] == "rules")
    assert top["input_hash"] == rules["input_hash"]

    # The model got the job as untrusted data and no personal details.
    call = claude.calls[0]
    assert call["model"] == "claude-haiku-5-5"
    user = call["messages"][0]["content"]
    assert "<job>" in user and "Jordan" not in user and "San Francisco, CA" in user
    candidate = json.loads(user.split("Candidate: ", 1)[1].split("\n\n", 1)[0])
    assert set(candidate) == {"seniority", "years_experience", "skills", "target_roles",
                              "related_roles"}  # fmt: skip

    run = await fetch_one(
        "SELECT * FROM agent_runs WHERE agent_name = 'agent_5_job_scoring' AND status = 'succeeded'"
    )
    assert run["input_tokens"] == 2000 and run["output_tokens"] == 400 and run["cost_usd"] > 0
    assert run["output_summary"]["claude"]["calls"] == 2

    # Nothing changed: no new Claude calls.
    await app.state.pipeline.rescore()
    assert len(claude.calls) == 2


async def test_claude_score_goes_stale_when_inputs_change_and_cache_is_used(app, claude):
    best, _, _ = await _claude_ready(app, claude_scoring_min_score=70)
    claude.responses = [claude_answer(91), claude_answer(80)]
    await app.state.pipeline.rescore()
    assert len(claude.calls) == 2
    # Equal rule scores are ordered by job id, so either answer may be this job's.
    original = next(r for r in await scores(best) if r["scoring_method"] == "claude")
    assert original["overall_score"] in (91, 80)

    # The posting changes: rules re-score, the Claude row no longer matches...
    await execute("UPDATE jobs SET description = description || ' Kafka.' WHERE id = :id", id=best)
    claude.responses = [claude_answer(60)]
    await app.state.pipeline.rescore()
    assert len(claude.calls) == 3  # ...so that one job is sent again
    claude_row = next(r for r in await scores(best) if r["scoring_method"] == "claude")
    assert claude_row["overall_score"] == 60

    # Reverting the change hits the cache: free, and recorded as cached.
    await execute(
        "UPDATE jobs SET description = replace(description, ' Kafka.', '') WHERE id = :id", id=best
    )
    await app.state.pipeline.rescore()
    assert len(claude.calls) == 3
    claude_row = next(r for r in await scores(best) if r["scoring_method"] == "claude")
    assert claude_row["overall_score"] == original["overall_score"]
    assert claude_row["breakdown"]["cached"] is True
    assert claude_row["input_tokens"] == 0


async def test_claude_limits_per_run_and_per_day(app, claude):
    await _claude_ready(app, claude_scoring_min_score=0)
    app.state.scoring.settings = app.state.scoring.settings.model_copy(
        update={"claude_scoring_max_per_run": 1, "claude_scoring_max_per_day": 2}
    )
    claude.responses = [claude_answer(90), claude_answer(85), claude_answer(80)]

    # Each run records its real calls in agent_runs; the daily cap counts them.
    for _ in range(3):
        assert (await app.state.pipeline.rescore())["pipeline_ok"]
    runs = await fetch(
        "SELECT output_summary FROM agent_runs WHERE agent_name = 'agent_5_job_scoring' "
        "ORDER BY started_at"
    )
    claude_runs = [r["output_summary"]["claude"] for r in runs]
    assert [c["calls"] for c in claude_runs] == [1, 1, 0]  # 1 per run, then the day is spent
    assert claude_runs[-1]["stopped"] == "daily or per-run limit reached"
    assert len(claude.calls) == 2


async def test_claude_failures_never_break_rule_scores(app, claude):
    await _claude_ready(app, claude_scoring_min_score=0)
    claude.responses = [
        LLMRefusalError("Claude declined this request."),
        claude_answer(80),
        _rate_limited(),
    ]
    result = await app.state.scoring.run()
    c = result["claude"]
    assert c["failed"] == 1 and c["scored"] == 1
    assert c["stopped"] == "Claude rate limit reached; try again shortly."
    assert result["rules"]["scored"] == 3
    assert len([r for r in await scores() if r["scoring_method"] == "claude"]) == 1


async def test_claude_needs_an_api_key(build_live_app):
    await reset_settings()
    try:
        app = build_live_app()  # no ANTHROPIC_API_KEY
        await _claude_ready(app)
        result = await app.state.scoring.run()
        assert result["claude"] == {
            "enabled": False, "reason": "no ANTHROPIC_API_KEY configured", "candidates": 0,
            "scored": 0, "calls": 0, "cached": 0, "failed": 0, "stopped": None, "errors": [],
        }  # fmt: skip
        assert result["rules"]["scored"] == 3
    finally:
        await reset_settings()


def _rate_limited():
    import anthropic

    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return anthropic.RateLimitError(
        "rate limited", response=httpx.Response(429, request=request), body=None
    )


# ============================================================ full pipeline
@respx.mock
async def test_full_pipeline_discovers_dedupes_filters_and_scores(app, client_for):
    respx.get(f"{GH}/acme").mock(
        return_value=httpx.Response(
            200, json=json.loads((FIX / "greenhouse_board.json").read_text())
        )
    )
    respx.get(f"{GH}/acme/jobs").mock(
        return_value=httpx.Response(
            200, json=json.loads((FIX / "greenhouse_jobs.json").read_text())
        )
    )
    await add_profile()
    async with client_for(app) as c:
        r = await c.post("/api/v1/companies", json={"source": "greenhouse", "slug": "acme"})
        assert r.status_code == 201
        started = await c.post("/api/v1/discovery/runs", json={})
        assert started.status_code == 202
        await app.state.task_manager.wait(started.json()["task_id"], timeout=30)

        info = app.state.task_manager.get(started.json()["task_id"])
        assert info.status == "succeeded", info.error
        stages = [s["stage"] for s in info.result["pipeline"]]
        assert stages == ["job_discovery", "agent_3_deduplication", "agent_4_rule_filtering",
                          "agent_5_job_scoring"]  # fmt: skip
        assert info.result["pipeline_ok"] and info.result["jobs_inserted"] == 3

        jobs = (await c.get("/api/v1/jobs", params={"sort": "score"})).json()["items"]
        assert len(jobs) == 3 and all(j["score"] is not None for j in jobs)
        assert all(j["score_method"] == "rules" and j["status"] == "scored" for j in jobs)
        assert [j["score"] for j in jobs] == sorted((j["score"] for j in jobs), reverse=True)

    runs = await fetch("SELECT agent_name, status FROM agent_runs ORDER BY started_at")
    names = [r["agent_name"] for r in runs]
    assert {"job_discovery", "agent_2_job_discovery", "agent_3_deduplication",
            "agent_4_rule_filtering", "agent_5_job_scoring"} <= set(names)  # fmt: skip
    assert all(r["status"] == "succeeded" for r in runs)


@respx.mock
async def test_scheduled_cycle_runs_the_whole_pipeline(app):
    from app.scheduler.tasks import run_discovery_cycle

    respx.get(f"{GH}/acme").mock(return_value=httpx.Response(200, json={"name": "Acme"}))
    respx.get(f"{GH}/acme/jobs").mock(
        return_value=httpx.Response(
            200, json=json.loads((FIX / "greenhouse_jobs.json").read_text())
        )
    )
    await add_profile()
    await execute(
        "INSERT INTO companies (name, source, slug) VALUES ('Acme', 'greenhouse', 'acme')"
    )
    result = await run_discovery_cycle(app.state.pipeline)
    assert result["skipped"] is False and result["pipeline_ok"] is True
    assert len(await scores()) == 3


async def test_pipeline_stops_after_a_failing_stage(app, monkeypatch):
    async def broken():
        raise RuntimeError("database exploded")

    monkeypatch.setattr(app.state.filtering, "run", broken)
    result = await app.state.pipeline.rescore()
    assert result["pipeline_ok"] is False
    assert [(s["stage"], s["ok"]) for s in result["pipeline"]] == [
        ("agent_3_deduplication", True), ("agent_4_rule_filtering", False),
    ]  # fmt: skip
    assert result["pipeline"][1]["error"] == "RuntimeError: database exploded"


def test_fake_response_shape_is_what_the_client_reads():
    # Guards the double the Claude tests rely on.
    r = FakeResponse(parsed_output=claude_answer())
    assert r.usage.input_tokens == 1000 and r.stop_reason == "end_turn"
