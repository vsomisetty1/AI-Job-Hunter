"""Connector interface: one implementation per job-board platform.

Every connector implements:

* `discover_jobs(board)`  fetch every open posting of one board (all pages)
* `normalize_job(raw)`    map one raw posting to a `NormalizedJob`
* `validate_job(job)`     list the problems that make a job unusable
* `health_check(board)`   probe the platform with a known board

Everything platform-specific (URLs, pagination, field names, quirks) lives
in the connector. Code outside connectors only sees `NormalizedJob`.
Adding a platform (e.g. Workday) = one new subclass + a registry entry.
"""

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar

from app.connectors.http import BoardNotFoundError, ConnectorError, HttpFetcher
from app.schemas.job import NormalizedJob


@dataclass(frozen=True)
class BoardInfo:
    slug: str
    name: str
    careers_url: str


@dataclass
class BoardFetch:
    """Raw postings of one board, as returned by the platform."""

    info: BoardInfo
    raw_jobs: list[dict[str, Any]]
    pages: int = 1
    expected_total: int | None = None
    notes: list[str] = field(default_factory=list)
    # False when the platform's answer looks truncated: discovery then does
    # not expire postings that are merely missing from this response.
    complete: bool = True


@dataclass(frozen=True)
class ConnectorHealth:
    source: str
    ok: bool
    board: str
    latency_ms: int
    jobs_visible: int | None = None
    error: str | None = None


def slug_to_name(slug: str) -> str:
    return " ".join(part.capitalize() for part in slug.replace("_", "-").split("-") if part)


class Connector(ABC):
    source: ClassVar[str]
    display_name: ClassVar[str]
    # A public board used by health_check() when no tracked company exists.
    health_board: ClassVar[str]

    def __init__(self, http: HttpFetcher) -> None:
        self.http = http

    # ------------------------------------------------------- interface
    @abstractmethod
    async def discover_jobs(self, board: str) -> BoardFetch: ...

    @abstractmethod
    def normalize_job(self, raw: dict[str, Any], *, board: BoardInfo) -> NormalizedJob: ...

    @abstractmethod
    def careers_url(self, board: str) -> str: ...

    async def board_info(self, board: str) -> BoardInfo:
        """Check that a board exists (cheaply where the platform allows) and name it."""
        return (await self.discover_jobs(board)).info

    def validate_job(self, job: NormalizedJob) -> list[str]:
        """Problems that make a job unusable (empty list = valid)."""
        problems = []
        if not job.source_job_id.strip():
            problems.append("missing job id")
        if not job.title.strip():
            problems.append("missing title")
        if not job.url.lower().startswith(("http://", "https://")):
            problems.append("missing or non-http URL")
        if job.apply_url and not job.apply_url.lower().startswith(("http://", "https://")):
            problems.append("non-http apply URL")
        if (
            job.salary_min is not None
            and job.salary_max is not None
            and job.salary_min > job.salary_max
        ):
            problems.append("salary range reversed")
        if job.salary_currency is not None and not (
            len(job.salary_currency) == 3 and job.salary_currency.isupper()
        ):
            problems.append("invalid currency")
        return problems

    async def health_check(self, board: str | None = None) -> ConnectorHealth:
        board = board or self.health_board
        start = time.perf_counter()
        try:
            fetched = await self.discover_jobs(board)
        except ConnectorError as exc:
            return ConnectorHealth(
                self.source, False, board, int((time.perf_counter() - start) * 1000),
                error=("board not found" if isinstance(exc, BoardNotFoundError) else str(exc)),
            )  # fmt: skip
        return ConnectorHealth(
            self.source, True, board, int((time.perf_counter() - start) * 1000),
            jobs_visible=len(fetched.raw_jobs),
        )  # fmt: skip

    # --------------------------------------------------------- helpers
    def normalize_all(
        self, fetched: BoardFetch
    ) -> tuple[list[NormalizedJob], list[tuple[str, list[str]]]]:
        """Normalize + validate a board. Returns (valid jobs, [(raw id, problems)])."""
        valid: list[NormalizedJob] = []
        invalid: list[tuple[str, list[str]]] = []
        for raw in fetched.raw_jobs:
            raw_id = str(raw.get("id", "?"))
            try:
                job = self.normalize_job(raw, board=fetched.info)
            except (KeyError, TypeError, ValueError) as exc:
                invalid.append((raw_id, [f"unreadable posting: {type(exc).__name__}: {exc}"]))
                continue
            problems = self.validate_job(job)
            if problems:
                invalid.append((raw_id, problems))
            else:
                valid.append(job)
        return valid, invalid
