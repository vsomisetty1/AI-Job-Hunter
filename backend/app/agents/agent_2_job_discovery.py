"""Agent 2: job discovery for one company board (network only, no database).

Fetches every posting through the platform's connector, normalizes and
validates them. Persistence and deduplication happen afterwards in
`app.services.discovery_service`, in a short transaction.
"""

import logging
import time
from dataclasses import dataclass, field

from app.connectors.base import BoardInfo, Connector
from app.connectors.http import BoardNotFoundError, ConnectorError
from app.schemas.job import NormalizedJob

logger = logging.getLogger(__name__)

MAX_INVALID_SAMPLES = 10


@dataclass
class BoardResult:
    source: str
    slug: str
    ok: bool
    info: BoardInfo | None = None
    jobs: list[NormalizedJob] = field(default_factory=list)
    found: int = 0
    invalid: list[dict[str, object]] = field(default_factory=list)
    invalid_count: int = 0
    pages: int = 0
    complete: bool = False
    notes: list[str] = field(default_factory=list)
    error: str | None = None
    not_found: bool = False
    duration_ms: int = 0


async def fetch_board(connector: Connector, slug: str) -> BoardResult:
    start = time.perf_counter()
    result = BoardResult(connector.source, slug, ok=False)
    try:
        fetched = await connector.discover_jobs(slug)
    except BoardNotFoundError:
        result.error, result.not_found = "board not found (check the slug)", True
    except ConnectorError as exc:
        result.error = str(exc)
    else:
        valid, invalid = connector.normalize_all(fetched)
        result.ok = True
        result.info = fetched.info
        result.jobs = valid
        result.found = len(fetched.raw_jobs)
        result.invalid_count = len(invalid)
        result.invalid = [{"id": i, "problems": p} for i, p in invalid[:MAX_INVALID_SAMPLES]]
        result.pages = fetched.pages
        result.complete = fetched.complete
        result.notes = fetched.notes
    result.duration_ms = int((time.perf_counter() - start) * 1000)
    if not result.ok:
        logger.warning("discovery failed for %s/%s: %s", connector.source, slug, result.error)
    return result
