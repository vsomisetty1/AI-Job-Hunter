"""FastAPI application entrypoint.

Run with `python -m app` (see app/__main__.py): it binds the configured host
and always uses a single worker, which the in-process scheduler requires.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import Settings, get_settings
from app.core.database import configure_database, dispose_engine
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import REQUEST_ID_HEADER, RequestContextMiddleware
from app.routers import api_v1_router, health_router
from app.scheduler.background import BackgroundTaskManager
from app.scheduler.scheduler import SchedulerService
from app.scheduler.tasks import register_jobs

logger = logging.getLogger(__name__)

OPENAPI_TAGS = [
    {"name": "health", "description": "Liveness and readiness probes (no auth)."},
    {"name": "settings", "description": "Job-search preferences (single row)."},
    {"name": "system", "description": "App info, scheduled jobs and background tasks."},
]

DESCRIPTION = """
Backend for AI Job Hunter, a personal, single-user job-search agent.

**Auth.** With `AUTH_MODE=none` (default, loopback only) no credentials are
needed. With `AUTH_MODE=api_key`, send `X-API-Key: <key>` or
`Authorization: Bearer <key>`.

**Errors.** Every error has the shape
`{"error": {"code": str, "message": str, "details": any}}`.

**Versioning.** Resource routes live under `/api/v1`.
"""


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    configure_database(settings)
    app.state.task_manager = BackgroundTaskManager()
    app.state.scheduler = SchedulerService(enabled=settings.scheduler_enabled)
    register_jobs(app.state.scheduler, settings)
    app.state.scheduler.start()
    logger.info(
        "%s %s started (env=%s, auth=%s)",
        settings.app_name,
        settings.app_version,
        settings.app_env,
        settings.auth_mode,
    )
    try:
        yield
    finally:
        app.state.scheduler.shutdown()
        await app.state.task_manager.shutdown()
        await dispose_engine()
        logger.info("shutdown complete")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, json_logs=settings.json_logs)

    docs = settings.docs_enabled
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=DESCRIPTION,
        openapi_tags=OPENAPI_TAGS,
        openapi_url=f"{settings.api_v1_prefix}/openapi.json" if docs else None,
        docs_url=f"{settings.api_v1_prefix}/docs" if docs else None,
        redoc_url=f"{settings.api_v1_prefix}/redoc" if docs else None,
        swagger_ui_oauth2_redirect_url=f"{settings.api_v1_prefix}/docs/oauth2-redirect",
        swagger_ui_parameters={"persistAuthorization": True},
        lifespan=lifespan,
    )
    app.state.settings = settings

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-API-Key", REQUEST_ID_HEADER],
        expose_headers=[REQUEST_ID_HEADER],
    )
    # Added last = outermost: request ids cover CORS and error responses too.
    app.add_middleware(RequestContextMiddleware)

    register_exception_handlers(app)
    app.include_router(health_router)
    app.include_router(api_v1_router, prefix=settings.api_v1_prefix)
    return app


def __getattr__(name: str) -> FastAPI:
    # `app` is built on first access (uvicorn app.main:app), so importing this
    # module in tests does not require DATABASE_URL or configure logging.
    if name == "app":
        global app
        app = create_app()
        return app
    raise AttributeError(name)
