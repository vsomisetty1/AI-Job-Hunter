"""Agent activity API (/agent-runs): list with filters, per-agent summary."""

from sqlalchemy import text

INSERT = text(
    "INSERT INTO agent_runs (agent_name, status, input_tokens, output_tokens, cost_usd, "
    "started_at, finished_at, duration_ms, error) VALUES (:a, :s, :i, :o, :c, "
    "now() - make_interval(days => :ago), "
    "CASE WHEN :s = 'running' THEN NULL ELSE now() - make_interval(days => :ago) END, :d, :e)"
)


async def seed(conn) -> None:
    rows = [
        ("job_scoring", "succeeded", 100, 20, 0.0012, 0, 40, None),
        ("job_scoring", "failed", 0, 0, 0, 1, 10, "timeout"),
        ("job_scoring", "succeeded", 50, 10, 0.0008, 40, 30, None),  # outside 30 days
        ("resume_parser", "running", 0, 0, 0, 0, None, None),
        ("cover_letters", "succeeded", 0, 0, 0, 2, 200, None),
    ]
    for a, s, i, o, c, ago, d, e in rows:
        await conn.execute(
            INSERT, {"a": a, "s": s, "i": i, "o": o, "c": c, "ago": ago, "d": d, "e": e}
        )


async def test_list_newest_first_with_filters(db_app, client_for):
    await seed(db_app.state.test_connection)
    async with client_for(db_app) as c:
        everything = (await c.get("/api/v1/agent-runs")).json()
        scoring = (await c.get("/api/v1/agent-runs?agent=job_scoring")).json()
        failed = (await c.get("/api/v1/agent-runs?status=failed")).json()
        page = (await c.get("/api/v1/agent-runs?limit=2&offset=1")).json()
        bad = await c.get("/api/v1/agent-runs?status=exploded")
    assert everything["total"] == 5
    starts = [r["started_at"] for r in everything["items"]]
    assert starts == sorted(starts, reverse=True)
    assert scoring["total"] == 3 and {r["agent_name"] for r in scoring["items"]} == {"job_scoring"}
    assert failed["total"] == 1 and failed["items"][0]["error"] == "timeout"
    assert len(page["items"]) == 2 and page["offset"] == 1
    assert bad.status_code == 422
    first = everything["items"][0]
    assert isinstance(first["cost_usd"], float) and "input_summary" in first


async def test_summary_per_agent_over_the_period(db_app, client_for):
    await seed(db_app.state.test_connection)
    async with client_for(db_app) as c:
        body = (await c.get("/api/v1/agent-runs/summary?days=30")).json()
        all_time = (await c.get("/api/v1/agent-runs/summary?days=365")).json()
        names = (await c.get("/api/v1/agent-runs/agents")).json()
    by = {a["agent_name"]: a for a in body["agents"]}
    assert body["days"] == 30 and body["total_runs"] == 4 and body["failed_runs"] == 1
    assert by["job_scoring"]["runs"] == 2 and by["job_scoring"]["failed"] == 1
    assert by["job_scoring"]["input_tokens"] == 100
    assert by["job_scoring"]["avg_duration_ms"] == 25
    assert by["resume_parser"]["running"] == 1
    assert abs(body["total_cost_usd"] - 0.0012) < 1e-9
    assert all_time["total_runs"] == 5
    assert names == ["cover_letters", "job_scoring", "resume_parser"]


async def test_summary_with_no_runs(db_app, client_for):
    async with client_for(db_app) as c:
        body = (await c.get("/api/v1/agent-runs/summary")).json()
    assert body == {
        "days": 30, "agents": [], "total_runs": 0, "failed_runs": 0, "total_cost_usd": 0.0
    }  # fmt: skip
