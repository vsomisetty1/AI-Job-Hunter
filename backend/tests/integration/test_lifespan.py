"""App startup/shutdown (lifespan) against a real database.

httpx's ASGITransport skips lifespan events, so the other API tests set app
state by hand; this test runs the real lifespan.
"""

from app.core import database
from app.scheduler.tasks import (
    AUTOMATION_SWEEP_JOB_ID,
    DISCOVERY_JOB_ID,
    LEARNING_JOB_ID,
    MAINTENANCE_JOB_ID,
)


async def test_lifespan_starts_and_stops_everything(make_app, client_for, migrated_db_url):
    app = make_app(database_url=migrated_db_url, scheduler_enabled=True)

    async with app.router.lifespan_context(app):
        scheduler = app.state.scheduler
        assert scheduler.running
        assert sorted(j.id for j in scheduler.list_jobs()) == sorted(
            [DISCOVERY_JOB_ID, MAINTENANCE_JOB_ID, AUTOMATION_SWEEP_JOB_ID, LEARNING_JOB_ID]
        )
        automation = app.state.automation
        assert not automation.browser.alive  # Chromium starts on the first run, not at boot
        assert database._engine is not None
        assert str(database._engine.url).startswith("postgresql+asyncpg://")

        async with client_for(app) as c:
            ready = await c.get("/health/ready")
            jobs = await c.get("/api/v1/system/jobs")
        assert ready.status_code == 200, ready.text
        assert ready.json()["checks"]["scheduler"] == {"ok": True, "detail": "running"}
        assert jobs.json()[0]["next_run_at"] is not None

        task_manager = app.state.task_manager

    assert not scheduler.running
    assert database._engine is None  # pool disposed
    assert not automation.browser.alive and automation.registry.open_count == 0
    # Task manager refuses new work after shutdown.
    try:
        task_manager.submit("late", lambda: None)  # type: ignore[arg-type]
    except RuntimeError:
        pass
    else:
        raise AssertionError("task manager accepted work after shutdown")


async def test_lifespan_with_scheduler_disabled(make_app, client_for, migrated_db_url):
    app = make_app(database_url=migrated_db_url, scheduler_enabled=False)
    async with app.router.lifespan_context(app):
        assert not app.state.scheduler.running
        async with client_for(app) as c:
            ready = await c.get("/health/ready")
        # A deliberately disabled scheduler does not make the app unready.
        assert ready.status_code == 200
        assert ready.json()["checks"]["scheduler"] == {"ok": True, "detail": "disabled"}
