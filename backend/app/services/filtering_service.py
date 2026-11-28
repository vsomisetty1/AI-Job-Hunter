"""Filtering: cross-board deduplication and Agent 4's rule filter over stored jobs.

* `mark_duplicates()` links jobs that another board already supplied
  (`jobs.duplicate_of`). Per-company deduplication happens during discovery;
  this sweep also catches duplicates inserted by concurrent crawls, which
  cannot see each other's uncommitted rows.
* `run()` evaluates every open job against the user's settings in keyset
  pages, one short transaction per page. The decision is stored on the job
  (`filter_result`, `filter_reason`, `filter_hash`, `filtered_at`), and the
  status moves between 'new'/'scored' (kept) and 'filtered' (dropped). Jobs
  whose fingerprint (rules version + settings + job fields) is unchanged are
  skipped, so a rerun with nothing new writes nothing.

Shortlisted, skipped, applied and expired jobs are user decisions or final,
and are never re-filtered.
"""

import logging
from collections import Counter
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.agent_4_rule_filtering import (
    FilterJob,
    FilterPreferences,
    evaluate,
    fingerprint,
)
from app.models.setting import Setting
from app.repositories.job_repository import FilterCandidate, JobRepository
from app.repositories.settings_repository import SettingsRepository

logger = logging.getLogger(__name__)

PAGE_SIZE = 500


def preferences_from(settings: Setting) -> FilterPreferences:
    return FilterPreferences(
        preferred_locations=tuple(settings.preferred_locations),
        remote_preference=settings.remote_preference,
        job_types=tuple(settings.job_types),
        salary_min=settings.salary_min,
        salary_currency=settings.salary_currency,
        requires_sponsorship=settings.requires_sponsorship,
        excluded_companies=tuple(settings.excluded_companies),
        excluded_keywords=tuple(settings.excluded_keywords),
    )


def filter_job(c: FilterCandidate) -> FilterJob:
    return FilterJob(
        title=c.title,
        company_name=c.company_name,
        location=c.location,
        remote_type=c.remote_type,
        employment_type=c.employment_type,
        salary_min=c.salary_min,
        salary_max=c.salary_max,
        salary_currency=c.salary_currency,
        description=c.description,
        requirements=tuple(str(r) for r in c.requirements),
        duplicate_of=str(c.duplicate_of) if c.duplicate_of else None,
    )


def next_status(current: str, passed: bool) -> str:
    if not passed:
        return "filtered"
    return "new" if current == "filtered" else current


class FilteringService:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self.sessionmaker = sessionmaker

    async def mark_duplicates(self) -> dict[str, int]:
        async with self.sessionmaker() as session, session.begin():
            result = await JobRepository(session).mark_cross_board_duplicates()
        if result["marked"] or result["released"]:
            logger.info("cross-board duplicates updated", extra=result)
        return result

    async def run(self) -> dict[str, Any]:
        async with self.sessionmaker() as session, session.begin():
            prefs = preferences_from(await SettingsRepository(session).get_singleton())

        counts: Counter[str] = Counter()
        reasons: Counter[str] = Counter()
        after = None
        while True:
            async with self.sessionmaker() as session, session.begin():
                repo = JobRepository(session)
                page = await repo.filter_candidates(after=after, limit=PAGE_SIZE)
                if not page:
                    break
                updates = []
                now = datetime.now(UTC)
                for c in page:
                    job = filter_job(c)
                    decision = evaluate(job, prefs)
                    for failure in decision.failures:
                        reasons[failure.rule] += 1
                    counts["passed" if decision.passed else "rejected"] += 1
                    status = next_status(c.status, decision.passed)
                    digest = fingerprint(job, prefs)
                    if digest == c.filter_hash and status == c.status:
                        counts["unchanged"] += 1
                        continue
                    updates.append(
                        {
                            "id": c.id,
                            "status": status,
                            "filter_reason": decision.reason,
                            "filter_result": decision.as_json(),
                            "filter_hash": digest,
                            "filtered_at": now,
                        }
                    )
                await repo.apply_filter_results(updates)
                counts["updated"] += len(updates)
                after = page[-1].id
        summary = {
            "evaluated": counts["passed"] + counts["rejected"],
            "passed": counts["passed"],
            "rejected": counts["rejected"],
            "updated": counts["updated"],
            "unchanged": counts["unchanged"],
            "rejected_by_rule": dict(reasons),
        }
        logger.info(
            "rule filter: %s passed, %s rejected, %s updated",
            summary["passed"], summary["rejected"], summary["updated"],
        )  # fmt: skip
        return summary
