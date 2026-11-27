"""API routers.

Versioning: every resource route lives under `/api/v1` (Settings.api_v1_prefix)
and requires the current user. A breaking change gets a new `api_v2_router`
mounted alongside, so v1 clients keep working. Health probes are unversioned
and unauthenticated.

Routers for later phases (applications, insights, agent_runs) are added to
`api_v1_router` when they are implemented.
"""

from fastapi import APIRouter, Depends

from app.core.security import get_current_user
from app.routers import (
    automation,
    companies,
    discovery,
    health,
    jobs,
    packages,
    profile,
    resumes,
    scoring,
    settings,
    system,
)

api_v1_router = APIRouter(dependencies=[Depends(get_current_user)])
api_v1_router.include_router(resumes.router)
api_v1_router.include_router(profile.router)
api_v1_router.include_router(settings.router)
api_v1_router.include_router(jobs.router)
api_v1_router.include_router(companies.router)
api_v1_router.include_router(discovery.router)
api_v1_router.include_router(scoring.router)
api_v1_router.include_router(packages.router)
api_v1_router.include_router(automation.router)
api_v1_router.include_router(system.router)

health_router = health.router

__all__ = ["api_v1_router", "health_router"]
