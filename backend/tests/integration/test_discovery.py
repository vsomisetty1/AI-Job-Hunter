"""Discovery end to end against a real database, with job boards mocked by respx.

Board payloads are the realistic fixtures in tests/fixtures/boards (same
shapes as the live Greenhouse, Lever and Ashby APIs). Discovery commits for
real (concurrent sessions), so these tests use the live-pool app.
"""

import copy
import json
import uuid
from pathlib import Path

import httpx
import pytest
import respx
from sqlalchemy import text

from app.connectors.http import HttpFetcher, RetryPolicy
from app.core.database import get_engine
from app.services.discovery_service import DiscoveryInProgressError

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "boards"
GH = "https://boards-api.greenhouse.io/v1/boards"
LV = "https://api.lever.co/v0/postings"
LV_EU = "https://api.eu.lever.co/v0/postings"
AB = "https://api.ashbyhq.com/posting-api/job-board"


def load(name: str):
    return json.loads((FIX / name).read_text())


async def no_sleep(_seconds: float) -> None:
    return None


@pytest.fixture()
def app(build_live_app):
    http = HttpFetcher(retry=RetryPolicy(attempts=2), sleep=no_sleep)
    return build_live_app(http=http, discovery_concurrency=2)


@pytest.fixture()
async def client(app, client_for):
    async with client_for(app) as c:
        yield c


async def scalar(sql: str, **params):
    async with get_engine().connect() as conn:
        return (await conn.execute(text(sql), params)).scalar()


async def rows(sql: str, **params):
    async with get_engine().connect() as conn:
        return [dict(r._mapping) for r in await conn.execute(text(sql), params)]


def mock_greenhouse(board="acme", jobs=None):
    respx.get(f"{GH}/{board}").mock(
        return_value=httpx.Response(200, json=load("greenhouse_board.json"))
    )
    return respx.get(f"{GH}/{board}/jobs").mock(
        return_value=httpx.Response(200, json=jobs or load("greenhouse_jobs.json"))
    )


async def add(client, source: str, slug: str) -> dict:
    r = await client.post("/api/v1/companies", json={"source": source, "slug": slug})
    assert r.status_code == 201, r.text
    return r.json()


async def run(app, **kwargs) -> dict:
    return await app.state.discovery.run("manual", **kwargs)


# ------------------------------------------------------------- persistence
@respx.mock
async def test_first_run_inserts_and_repeat_run_changes_nothing(app, client):
    mock_greenhouse()
    company = await add(client, "greenhouse", "ACME")  # slug is lower-cased
    assert (company["slug"], company["name"]) == ("acme", "Acme Robotics")

    first = await run(app)
    assert first["status"] == "succeeded"
    detail = first["details"][0]
    # 4 postings on the board; one has a javascript: URL and fails validation.
    assert (detail["found"], detail["invalid"], detail["inserted"]) == (4, 1, 3)
    assert first["jobs_skipped"] == 1 and first["jobs_inserted"] == 3
    assert detail["invalid_samples"][0]["id"] == "4004"

    stored = await rows(
        "SELECT external_id, remote_type, employment_type, salary_min, salary_max, status, "
        "first_seen_at, last_seen_at, content_hash FROM jobs ORDER BY external_id"
    )
    assert [r["external_id"] for r in stored] == ["4001", "4002", "4003"]
    assert all(r["status"] == "new" and len(r["content_hash"]) == 64 for r in stored)
    assert all(r["first_seen_at"] == r["last_seen_at"] for r in stored)

    second = await run(app)
    assert (second["jobs_inserted"], second["jobs_updated"], second["jobs_unchanged"]) == (0, 0, 3)
    again = await rows("SELECT first_seen_at, last_seen_at FROM jobs ORDER BY external_id")
    for before, after in zip(stored, again, strict=True):
        assert after["first_seen_at"] == before["first_seen_at"]  # first_seen never moves
        assert after["last_seen_at"] > before["last_seen_at"]  # last_seen advances
    assert await scalar("SELECT count(*) FROM jobs") == 3

    company_row = (await rows("SELECT * FROM companies"))[0]
    assert company_row["last_crawl_status"] == "ok" and company_row["consecutive_failures"] == 0
    runs = await rows("SELECT status, trigger, jobs_found FROM discovery_runs ORDER BY started_at")
    assert runs == [{"status": "succeeded", "trigger": "manual", "jobs_found": 4}] * 2


@respx.mock
async def test_changes_expiry_and_revival(app, client):
    board = load("greenhouse_jobs.json")
    route = mock_greenhouse(jobs=board)
    await add(client, "greenhouse", "acme")
    await run(app)

    # 4001 changes, 4002 disappears from the board.
    changed = copy.deepcopy(board)
    changed["jobs"][0]["title"] = "Staff Backend Engineer"
    changed["jobs"] = [j for j in changed["jobs"] if j["id"] != 4002]
    changed["meta"]["total"] = len(changed["jobs"])
    route.mock(return_value=httpx.Response(200, json=changed))
    result = await run(app)
    assert (result["jobs_updated"], result["jobs_unchanged"], result["jobs_expired"]) == (1, 1, 1)
    status = {r["external_id"]: r for r in await rows("SELECT * FROM jobs")}
    assert status["4001"]["title"] == "Staff Backend Engineer"
    assert status["4002"]["status"] == "expired" and status["4002"]["expired_at"] is not None

    # Applied jobs are never expired.
    async with get_engine().begin() as conn:
        await conn.execute(text("UPDATE jobs SET status = 'applied' WHERE external_id = '4003'"))
    only_one = copy.deepcopy(changed)
    only_one["jobs"] = only_one["jobs"][:1] + only_one["jobs"][-1:]  # 4001 + invalid 4004
    only_one["meta"]["total"] = 2
    route.mock(return_value=httpx.Response(200, json=only_one))
    await run(app)
    assert await scalar("SELECT status FROM jobs WHERE external_id = '4003'") == "applied"

    # 4002 comes back: revived as new, not inserted twice.
    route.mock(return_value=httpx.Response(200, json=board))
    result = await run(app)
    revived = (await rows("SELECT * FROM jobs WHERE external_id = '4002'"))[0]
    assert (revived["status"], revived["expired_at"]) == ("new", None)
    assert result["jobs_inserted"] == 0 and await scalar("SELECT count(*) FROM jobs") == 3


@respx.mock
async def test_incomplete_response_never_expires(app, client):
    board = load("greenhouse_jobs.json")
    route = mock_greenhouse(jobs=board)
    await add(client, "greenhouse", "acme")
    await run(app)

    truncated = copy.deepcopy(board)
    truncated["jobs"] = truncated["jobs"][:1]
    truncated["meta"]["total"] = 4  # the board says 4, the response has 1
    route.mock(return_value=httpx.Response(200, json=truncated))
    result = await run(app)
    assert result["jobs_expired"] == 0
    assert "nothing was expired" in " ".join(result["details"][0]["notes"])
    assert await scalar("SELECT count(*) FROM jobs WHERE status = 'expired'") == 0


@respx.mock
async def test_an_empty_board_is_flagged(app, client):
    """A board that answers with no jobs (the company moved to another board)
    is crawled successfully but carries a note, so the user can spot it."""
    mock_greenhouse(jobs={"jobs": [], "meta": {"total": 0}})
    await add(client, "greenhouse", "acme")
    result = await run(app)
    detail = result["details"][0]
    assert detail["status"] == "ok" and detail["found"] == 0
    assert any("no open jobs" in n for n in detail["notes"])


@respx.mock
async def test_cross_board_and_url_duplicates_are_skipped(app, client):
    mock_greenhouse()
    await add(client, "greenhouse", "acme")
    await run(app)

    # The same employer also runs an Ashby board with one shared posting.
    board = load("ashby_board.json")
    twin = copy.deepcopy(board["jobs"][0])
    twin.update(id="dup-1", title="Sr. Backend Engineer",
                location="New York, NY; San Francisco, CA",
                jobUrl="https://jobs.ashbyhq.com/acme-robotics/dup-1",
                applyUrl="https://jobs.ashbyhq.com/acme-robotics/dup-1/application",
                secondaryLocations=[])  # fmt: skip
    same_url = copy.deepcopy(board["jobs"][1])
    same_url.update(id="dup-2", jobUrl="https://acme.example/careers?gh_jid=4002")
    board["jobs"] += [twin, same_url]
    respx.get(f"{AB}/acme-robotics").mock(return_value=httpx.Response(200, json=board))
    await add(client, "ashby", "acme-robotics")

    result = await run(app)
    ashby = next(d for d in result["details"] if d["source"] == "ashby")
    assert ashby["inserted"] == 2  # two listed, original postings
    assert ashby["skip_reasons"] == {
        "same job already found on another board": 1,
        "URL already belongs to another job": 1,
    }
    assert ashby["invalid"] == 0 and ashby["found"] == 4  # the unlisted one is not "found"
    assert await scalar("SELECT count(*) FROM jobs") == 5


# -------------------------------------------------------- failure handling
@respx.mock
async def test_one_failing_board_does_not_stop_others(app, client):
    mock_greenhouse()
    await add(client, "greenhouse", "acme")
    respx.get(f"{LV}/acme").mock(return_value=httpx.Response(200, json=[]))
    lever = await add(client, "lever", "acme")
    respx.get(f"{LV}/acme").mock(return_value=httpx.Response(404, json={"ok": False}))
    respx.get(f"{LV_EU}/acme").mock(return_value=httpx.Response(404, json={"ok": False}))

    result = await run(app)
    assert result["companies_succeeded"] == 1 and result["companies_failed"] == 1
    run_row = (await rows("SELECT status, error FROM discovery_runs"))[0]
    assert run_row == {"status": "partial", "error": "1 of 2 companies failed"}
    assert await scalar("SELECT count(*) FROM jobs") == 3

    await run(app, company_ids=[uuid.UUID(lever["id"])])
    row = (await rows("SELECT * FROM companies WHERE id = :id", id=lever["id"]))[0]
    assert (row["last_crawl_status"], row["consecutive_failures"]) == ("not_found", 2)
    assert "not found" in row["last_error"]


@respx.mock
async def test_server_errors_are_retried_then_recorded(app, client):
    mock_greenhouse()
    await add(client, "greenhouse", "acme")
    route = respx.get(f"{GH}/acme/jobs").mock(return_value=httpx.Response(503))
    result = await run(app)
    assert route.call_count == 2  # RetryPolicy(attempts=2)
    assert result["status"] == "failed" and result["details"][0]["status"] == "error"
    assert await scalar("SELECT last_crawl_status FROM companies") == "error"

    route.mock(
        side_effect=[httpx.Response(502), httpx.Response(200, json=load("greenhouse_jobs.json"))]
    )
    result = await run(app)
    assert result["status"] == "succeeded"
    assert await scalar("SELECT consecutive_failures FROM companies") == 0


async def test_only_one_run_at_a_time(app, client):
    async with get_engine().begin() as conn:
        await conn.execute(text("INSERT INTO discovery_runs (trigger) VALUES ('scheduled')"))
    with pytest.raises(DiscoveryInProgressError):
        await app.state.discovery.start("manual")
    r = await client.post("/api/v1/discovery/runs", json={})
    assert r.status_code == 409 and r.json()["error"]["code"] == "discovery_in_progress"


# ----------------------------------------------------- scheduled/incremental
@respx.mock
async def test_scheduled_refresh_only_crawls_due_companies(app, client):
    from app.scheduler.tasks import run_discovery_cycle

    route = mock_greenhouse()
    await add(client, "greenhouse", "acme")
    first = await run_discovery_cycle(app.state.pipeline)
    assert first["skipped"] is False and first["companies_total"] == 1
    assert route.call_count == 1

    # Crawled just now: not due, nothing fetched.
    second = await run_discovery_cycle(app.state.pipeline)
    assert second["companies_total"] == 0 and route.call_count == 1

    async with get_engine().begin() as conn:
        await conn.execute(text("UPDATE companies SET last_crawled_at = now() - interval '1 day'"))
    third = await run_discovery_cycle(app.state.pipeline)
    assert third["companies_total"] == 1 and route.call_count == 2
    triggers = await scalar("SELECT string_agg(DISTINCT trigger, ',') FROM discovery_runs")
    assert triggers == "scheduled"


@respx.mock
async def test_untracked_companies_are_not_crawled(app, client):
    route = mock_greenhouse()
    company = await add(client, "greenhouse", "acme")
    r = await client.patch(f"/api/v1/companies/{company['id']}", json={"is_tracked": False})
    assert r.status_code == 200 and r.json()["is_tracked"] is False
    result = await run(app)
    assert result["companies_total"] == 0 and route.call_count == 0


# ------------------------------------------------------------------- API
@respx.mock
async def test_discovery_api_flow(app, client):
    mock_greenhouse()
    await add(client, "greenhouse", "acme")

    r = await client.post("/api/v1/discovery/runs")
    assert r.status_code == 202, r.text
    started = r.json()
    info = await app.state.task_manager.wait(started["task_id"], timeout=60)
    assert info.status == "succeeded", info.error

    run_detail = (await client.get(f"/api/v1/discovery/runs/{started['run_id']}")).json()
    assert run_detail["status"] == "succeeded" and run_detail["jobs_inserted"] == 3
    assert run_detail["details"][0]["slug"] == "acme"
    listed = (await client.get("/api/v1/discovery/runs?limit=5")).json()
    assert listed["total"] == 1 and "details" not in listed["items"][0]
    missing = await client.get("/api/v1/discovery/runs/00000000-0000-0000-0000-000000000000")
    assert missing.status_code == 404

    jobs = (await client.get("/api/v1/jobs")).json()
    assert jobs["total"] == 3
    assert {j["company_name"] for j in jobs["items"]} == {"Acme Robotics"}
    found = (await client.get("/api/v1/jobs", params={"q": "backend"})).json()
    assert [j["external_id"] for j in found["items"]] == ["4001"]
    remote = (await client.get("/api/v1/jobs", params={"remote_type": "remote"})).json()
    assert [j["external_id"] for j in remote["items"]] == ["4002"]
    assert (await client.get("/api/v1/jobs", params={"q": "100%_"})).json()["total"] == 0
    page = (
        await client.get("/api/v1/jobs", params={"limit": 1, "offset": 1, "sort": "title"})
    ).json()
    assert (page["total"], len(page["items"])) == (3, 1)

    job_id = found["items"][0]["id"]
    detail = (await client.get(f"/api/v1/jobs/{job_id}")).json()
    assert detail["description"] and "<" not in detail["description"]
    assert detail["requirements"]
    raw = (await client.get(f"/api/v1/jobs/{job_id}/raw")).json()
    assert raw["source"] == "greenhouse" and raw["raw"]["id"] == 4001
    assert (await client.get(f"/api/v1/jobs/{job_id}x")).status_code == 422

    stats = (await client.get("/api/v1/jobs/stats")).json()
    assert stats["source"] == {"greenhouse": 3} and stats["status"] == {"new": 3}

    health = (await client.get("/api/v1/discovery/health")).json()
    gh = next(h for h in health if h["source"] == "greenhouse")
    assert (gh["companies_tracked"], gh["jobs_active"], gh["probe"]) == (1, 3, None)
    assert {h["source"] for h in health} == {"greenhouse", "lever", "ashby"}


@respx.mock
async def test_health_probe_calls_each_platform(app, client):
    mock_greenhouse()
    await add(client, "greenhouse", "acme")
    respx.get(f"{LV}/lever").mock(
        return_value=httpx.Response(200, json=load("lever_postings.json"))
    )
    respx.get(f"{AB}/ashby").mock(return_value=httpx.Response(500))
    health = (await client.get("/api/v1/discovery/health", params={"probe": True})).json()
    probes = {h["source"]: h["probe"] for h in health}
    assert probes["greenhouse"]["ok"] and probes["greenhouse"]["board"] == "acme"
    assert probes["lever"]["ok"] and probes["lever"]["jobs_visible"] == 5
    assert probes["ashby"]["ok"] is False and probes["ashby"]["error"]


@respx.mock
async def test_company_api(app, client):
    respx.get(f"{GH}/nope").mock(return_value=httpx.Response(404, json={"status": 404}))
    r = await client.post("/api/v1/companies", json={"source": "greenhouse", "slug": "nope"})
    assert r.status_code == 422 and "job-boards.greenhouse.io" in r.json()["error"]["message"]
    respx.get(f"{GH}/down").mock(return_value=httpx.Response(503))
    r = await client.post("/api/v1/companies", json={"source": "greenhouse", "slug": "down"})
    assert r.status_code == 502 and r.json()["error"]["code"] == "board_unavailable"
    r = await client.post("/api/v1/companies", json={"source": "workday", "slug": "x"})
    assert r.status_code == 422

    mock_greenhouse()
    company = await add(client, "greenhouse", "acme")
    dup = await client.post("/api/v1/companies", json={"source": "greenhouse", "slug": "acme"})
    assert dup.status_code == 409

    directory = (await client.get("/api/v1/companies/directory")).json()
    assert len(directory) >= 20 and not any(d["added"] for d in directory)
    pick = [{"source": d["source"], "slug": d["slug"]} for d in directory[:2]]
    added = await client.post("/api/v1/companies/suggested", json={"boards": pick * 2})
    assert added.status_code == 201 and len(added.json()) == 2  # repeats ignored
    again = await client.post("/api/v1/companies/suggested", json={"boards": pick})
    assert again.json() == []
    bad = await client.post(
        "/api/v1/companies/suggested", json={"boards": [{"source": "lever", "slug": "unknown"}]}
    )
    assert bad.status_code == 422
    directory = (await client.get("/api/v1/companies/directory")).json()
    assert sum(d["added"] for d in directory) == 2

    listed = (await client.get("/api/v1/companies")).json()
    assert len(listed) == 3 and all("active_jobs" in c for c in listed)

    renamed = await client.patch(f"/api/v1/companies/{company['id']}", json={"name": "Acme"})
    assert renamed.json()["name"] == "Acme"
    await run(app, company_ids=[uuid.UUID(company["id"])])
    blocked = await client.delete(f"/api/v1/companies/{company['id']}")
    assert blocked.status_code == 409  # it has jobs: stop tracking instead
    other = next(c for c in listed if c["id"] != company["id"])
    assert (await client.delete(f"/api/v1/companies/{other['id']}")).status_code == 204
    assert (await client.delete(f"/api/v1/companies/{other['id']}")).status_code == 404
