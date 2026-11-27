"""Phase 3 backend foundation against a real database.

Needs TEST_DATABASE_URL (see tests/conftest.py); skipped otherwise.
"""

import pytest
from sqlalchemy import delete, select, text

from app.agents.runs import AgentRunHandle, track_agent_run
from app.core.database import get_sessionmaker
from app.models.agent_run import AgentRun
from app.services.pipeline_service import PipelineService


async def test_readiness_reports_database_and_migrations(db_app, client_for):
    async with client_for(db_app) as c:
        r = await c.get("/health/ready")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ready"
    assert body["checks"]["database"]["ok"] and body["checks"]["migrations"]["ok"]


async def test_readiness_fails_when_database_unreachable(make_app, client_for):
    from app.core.database import configure_database, dispose_engine

    app = make_app(database_url="postgresql://u:p@127.0.0.1:1/none")
    configure_database(app.state.settings)
    try:
        async with client_for(app) as c:
            r = await c.get("/health/ready")
    finally:
        await dispose_engine()
    assert r.status_code == 503
    assert r.json()["checks"]["database"]["ok"] is False


async def test_get_settings_returns_seeded_defaults(db_app, client_for):
    async with client_for(db_app) as c:
        r = await c.get("/api/v1/settings")
    assert r.status_code == 200
    body = r.json()
    assert body["application_mode"] == "APPROVAL_MODE"
    assert body["auto_apply_threshold"] == 80


async def test_patch_settings_persists_and_bumps_updated_at(db_app, client_for):
    async with client_for(db_app) as c:
        before = (await c.get("/api/v1/settings")).json()
        r = await c.patch(
            "/api/v1/settings",
            json={
                "excluded_companies": ["Acme", "acme"],
                "salary_min": 100000,
                "salary_currency": "eur",
            },
        )
        after = (await c.get("/api/v1/settings")).json()
    assert r.status_code == 200, r.text
    assert after["excluded_companies"] == ["Acme"]
    assert after["salary_min"] == 100000 and after["salary_currency"] == "EUR"
    assert after["updated_at"] > before["updated_at"]


async def test_partial_salary_update_checked_against_stored_value(db_app, client_for):
    async with client_for(db_app) as c:
        await c.patch("/api/v1/settings", json={"salary_target": 120000})
        r = await c.patch("/api/v1/settings", json={"salary_min": 150000})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"


async def test_failed_request_rolls_back(db_app, client_for):
    async with client_for(db_app) as c:
        await c.patch("/api/v1/settings", json={"salary_target": 120000})
        await c.patch("/api/v1/settings", json={"salary_min": 150000})  # rejected
        body = (await c.get("/api/v1/settings")).json()
    assert body["salary_min"] is None


async def test_settings_row_recreated_if_missing(db_app, client_for):
    await db_app.state.test_connection.execute(text("DELETE FROM settings"))
    async with client_for(db_app) as c:
        r = await c.get("/api/v1/settings")
    assert r.status_code == 200
    assert r.json()["daily_application_cap"] == 10


async def test_database_check_violation_maps_to_422(db_app, client_for):
    """If validation is ever bypassed, the DB CHECK still wins and maps to 422."""
    from fastapi import Depends

    from app.dependencies import get_db, get_settings_service
    from app.services.settings_service import SettingsService

    class Unchecked(SettingsService):
        async def update(self, patch):
            current = await self.repo.get_singleton()
            return await self.repo.update(current, {"daily_application_cap": 999})

    def _svc(db=Depends(get_db)):
        return Unchecked(db)

    db_app.dependency_overrides[get_settings_service] = _svc
    async with client_for(db_app) as c:
        r = await c.patch("/api/v1/settings", json={"daily_application_cap": 5})
    assert r.status_code == 422
    assert r.json()["error"]["details"] == {"constraint": "ck_settings_cap"}


async def _runs(ids):
    async with get_sessionmaker()() as s:
        return (await s.scalars(select(AgentRun).where(AgentRun.id.in_(ids)))).all()


async def _cleanup(ids):
    async with get_sessionmaker()() as s, s.begin():
        await s.execute(delete(AgentRun).where(AgentRun.id.in_(ids)))


async def test_track_agent_run_records_success_and_failure(db_app):
    ids = []
    try:
        async with track_agent_run("test_agent", input_summary={"n": 1}) as run:
            ids.append(run.id)
            run.add_usage(input_tokens=10, output_tokens=5, cost_usd=0.0012)
            run.output_summary = {"ok": True}

        with pytest.raises(ValueError):
            async with track_agent_run("test_agent") as run:
                ids.append(run.id)
                raise ValueError("bad input")

        ok, failed = sorted(await _runs(ids), key=lambda r: r.status, reverse=True)
        assert ok.status == "succeeded" and ok.input_tokens == 10 and ok.output_tokens == 5
        assert ok.output_summary == {"ok": True} and float(ok.cost_usd) == pytest.approx(0.0012)
        assert ok.finished_at >= ok.started_at and ok.duration_ms is not None
        assert failed.status == "failed" and failed.error == "ValueError: bad input"
    finally:
        await _cleanup(ids)


async def test_pipeline_runs_stages_in_order_and_stops_on_failure(db_app):
    calls = []

    class Stage:
        def __init__(self, name, fail=False):
            self.name, self.fail = name, fail

        async def run(self, context, run: AgentRunHandle):
            calls.append(self.name)
            if self.fail:
                raise RuntimeError("stage broke")
            context[self.name] = True
            return {"seen": sorted(context)}

    result = await PipelineService([Stage("a"), Stage("b", fail=True), Stage("c")]).run({})
    ids = [s.agent_run_id for s in result.stages]
    try:
        assert calls == ["a", "b"]
        assert not result.ok
        assert [s.ok for s in result.stages] == [True, False]
        assert result.stages[1].error == "RuntimeError: stage broke"
        statuses = {r.agent_name: r.status for r in await _runs(ids)}
        assert statuses == {"a": "succeeded", "b": "failed"}
    finally:
        await _cleanup(ids)


async def test_discovery_cycle_respects_setting(db_app, monkeypatch):
    from app.scheduler import tasks

    async with get_sessionmaker()() as s, s.begin():
        await s.execute(text("UPDATE settings SET discovery_enabled = false"))
    try:
        assert (await tasks.run_discovery_cycle())["skipped"] is True
    finally:
        async with get_sessionmaker()() as s, s.begin():
            await s.execute(text("UPDATE settings SET discovery_enabled = true"))
    assert (await tasks.run_discovery_cycle())["skipped"] is False
