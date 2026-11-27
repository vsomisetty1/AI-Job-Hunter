"""Health checks (unversioned, unauthenticated).

* GET /health        liveness: the process is up. Never touches the database.
* GET /health/ready  readiness: database reachable AND migrated to Alembic head.
"""

import logging
from functools import lru_cache
from typing import Literal

from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text

from app.core.database import get_engine
from app.core.paths import BACKEND_DIR

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/health", tags=["health"])


class LivenessResponse(BaseModel):
    status: Literal["ok"] = "ok"
    version: str
    environment: str


class CheckResult(BaseModel):
    ok: bool
    detail: str | None = None


class ReadinessResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    checks: dict[str, CheckResult]


@lru_cache
def alembic_head() -> str | None:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    return ScriptDirectory.from_config(cfg).get_current_head()


async def check_database() -> tuple[CheckResult, CheckResult]:
    """Return (database, migrations) check results."""
    try:
        async with get_engine().connect() as conn:
            await conn.execute(text("SELECT 1"))
            current = await conn.scalar(text("SELECT version_num FROM alembic_version"))
    except Exception as exc:  # noqa: BLE001 - reported, not raised
        logger.warning("readiness: database check failed: %s", exc)
        return CheckResult(ok=False, detail=type(exc).__name__), CheckResult(ok=False)
    head = alembic_head()
    if current != head:
        return CheckResult(ok=True), CheckResult(
            ok=False, detail=f"database at {current}, code expects {head}; run alembic upgrade head"
        )
    return CheckResult(ok=True), CheckResult(ok=True, detail=current)


@router.get("", response_model=LivenessResponse, summary="Liveness probe")
async def liveness(request: Request) -> LivenessResponse:
    s = request.app.state.settings
    return LivenessResponse(version=s.app_version, environment=s.app_env)


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    summary="Readiness probe",
    responses={503: {"model": ReadinessResponse, "description": "A dependency is not ready"}},
)
async def readiness(request: Request) -> JSONResponse:
    db, migrations = await check_database()
    scheduler = getattr(request.app.state, "scheduler", None)
    sched = CheckResult(
        ok=scheduler is None or not scheduler.enabled or scheduler.running,
        detail=None if scheduler is None else ("running" if scheduler.running else "disabled"),
    )
    checks = {"database": db, "migrations": migrations, "scheduler": sched}
    ready = all(c.ok for c in checks.values())
    body = ReadinessResponse(status="ready" if ready else "not_ready", checks=checks)
    return JSONResponse(body.model_dump(), status_code=200 if ready else 503)
