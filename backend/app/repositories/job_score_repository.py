"""Score repository: scoring candidates, upserts, and the effective score.

The *effective* score of a job is the current Claude score when there is one
(a Claude row computed from the same inputs as the current rule-based row),
otherwise the rule-based score.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import ColumnElement, Select, and_, case, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import aliased

from app.models.agent_run import AgentRun
from app.models.company import Company
from app.models.job import Job
from app.models.job_score import JobScore
from app.repositories.base import Repository

# Jobs worth scoring: still open, not yet decided on by the user.
SCORABLE_STATUSES = ("new", "scored", "shortlisted")
SCORING_AGENT = "agent_5_job_scoring"

RulesRow = aliased(JobScore, name="rules_score")
ClaudeRow = aliased(JobScore, name="claude_score")

_UPSERT_EXCLUDE = {"id", "job_id", "profile_id", "scoring_method", "created_at"}


@dataclass(frozen=True)
class ScoringCandidate:
    job_id: uuid.UUID
    status: str
    title: str
    company_name: str
    location: str | None
    remote_type: str
    employment_type: str | None
    salary_min: int | None
    salary_max: int | None
    salary_currency: str | None
    description: str
    requirements: list[Any]
    rules_hash: str | None  # input hash of the stored rule-based score


@dataclass(frozen=True)
class ClaudeCandidate:
    job_id: uuid.UUID
    rules_hash: str
    rules_overall: int
    rules_breakdown: dict[str, Any]
    matched_skills: list[Any]
    missing_skills: list[Any]


def passed_filters() -> ColumnElement[bool]:
    """Filtered at least once, passed, and not a cross-board duplicate."""
    return and_(
        Job.filtered_at.is_not(None),
        Job.filter_result["passed"].as_boolean().is_(True),
        Job.duplicate_of.is_(None),
    )


def effective_score_join[*Ts](
    stmt: Select[*Ts], profile_id: ColumnElement[Any] | uuid.UUID | None
) -> Select[*Ts]:
    """LEFT JOIN the current rule-based and Claude rows of `profile_id`."""
    return stmt.outerjoin(
        RulesRow,
        and_(
            RulesRow.job_id == Job.id,
            RulesRow.profile_id == profile_id,
            RulesRow.scoring_method == "rules",
        ),
    ).outerjoin(
        ClaudeRow,
        and_(
            ClaudeRow.job_id == Job.id,
            ClaudeRow.profile_id == profile_id,
            ClaudeRow.scoring_method == "claude",
            ClaudeRow.input_hash == RulesRow.input_hash,
        ),
    )


def effective_score() -> ColumnElement[Any]:
    return func.coalesce(ClaudeRow.overall_score, RulesRow.overall_score)


def effective_method() -> ColumnElement[Any]:
    return case(
        (ClaudeRow.id.is_not(None), "claude"), (RulesRow.id.is_not(None), "rules"), else_=None
    )


class JobScoreRepository(Repository[JobScore]):
    model = JobScore

    # ------------------------------------------------------------ rule-based
    async def rules_candidates(
        self, profile_id: uuid.UUID, *, after: uuid.UUID | None, limit: int
    ) -> list[ScoringCandidate]:
        """One keyset page of jobs to (re)score, with their stored rule hash."""
        stmt = (
            select(
                Job.id,
                Job.status,
                Job.title,
                Company.name,
                Job.location,
                Job.remote_type,
                Job.employment_type,
                Job.salary_min,
                Job.salary_max,
                Job.salary_currency,
                Job.description,
                Job.requirements,
                RulesRow.input_hash,
            )  # fmt: skip
            .join(Company, Company.id == Job.company_id)
            .outerjoin(
                RulesRow,
                and_(
                    RulesRow.job_id == Job.id,
                    RulesRow.profile_id == profile_id,
                    RulesRow.scoring_method == "rules",
                ),
            )
            .where(Job.status.in_(SCORABLE_STATUSES), passed_filters())
            .order_by(Job.id)
            .limit(limit)
        )
        if after is not None:
            stmt = stmt.where(Job.id > after)
        rows = await self.session.execute(stmt)
        return [ScoringCandidate(*tuple(r)) for r in rows]

    async def upsert(self, rows: Sequence[dict[str, Any]]) -> None:
        """Insert or replace the (job, profile, method) rows. All dicts share keys."""
        if not rows:
            return
        stmt = insert(JobScore).values(list(rows))
        columns = [k for k in rows[0] if k not in _UPSERT_EXCLUDE]
        await self.session.execute(
            stmt.on_conflict_do_update(
                constraint="uq_job_scores_job_profile_method",
                set_={c: stmt.excluded[c] for c in columns} | {"updated_at": func.now()},
            )
        )

    async def mark_scored(self, job_ids: Sequence[uuid.UUID]) -> None:
        """New jobs become 'scored'; shortlisted/scored jobs keep their status."""
        if job_ids:
            await self.session.execute(
                update(Job)
                .where(Job.id.in_(list(job_ids)), Job.status == "new")
                .values(status="scored")
            )

    # ---------------------------------------------------------------- Claude
    async def claude_candidates(
        self, profile_id: uuid.UUID, *, min_score: int, prompt_version: str, limit: int
    ) -> list[ClaudeCandidate]:
        """Best rule-scored jobs that have no current Claude score."""
        if limit <= 0:
            return []
        stmt = (
            select(
                Job.id,
                RulesRow.input_hash,
                RulesRow.overall_score,
                RulesRow.breakdown,
                RulesRow.matched_skills,
                RulesRow.missing_skills,
            )
            .join(
                RulesRow,
                and_(
                    RulesRow.job_id == Job.id,
                    RulesRow.profile_id == profile_id,
                    RulesRow.scoring_method == "rules",
                ),
            )
            .outerjoin(
                ClaudeRow,
                and_(
                    ClaudeRow.job_id == Job.id,
                    ClaudeRow.profile_id == profile_id,
                    ClaudeRow.scoring_method == "claude",
                ),
            )
            .where(
                Job.status.in_(SCORABLE_STATUSES),
                passed_filters(),
                RulesRow.input_hash.is_not(None),
                RulesRow.overall_score >= min_score,
                or_(
                    ClaudeRow.id.is_(None),
                    ClaudeRow.input_hash.is_distinct_from(RulesRow.input_hash),
                    ClaudeRow.prompt_version.is_distinct_from(prompt_version),
                ),
            )
            .order_by(RulesRow.overall_score.desc(), Job.id)
            .limit(limit)
        )
        rows = await self.session.execute(stmt)
        return [ClaudeCandidate(*tuple(r)) for r in rows]

    async def claude_calls_since(self, since: datetime) -> int:
        """Real (uncached) Claude scoring calls recorded by scoring runs since `since`."""
        calls = AgentRun.output_summary["claude"]["calls"].as_integer()
        total = await self.session.scalar(
            select(func.coalesce(func.sum(calls), 0)).where(
                AgentRun.agent_name == SCORING_AGENT, AgentRun.started_at >= since
            )
        )
        return int(total or 0)

    # ------------------------------------------------------------------ reads
    async def for_job(self, job_id: uuid.UUID, profile_id: uuid.UUID) -> list[JobScore]:
        rows = await self.session.scalars(
            select(JobScore)
            .where(JobScore.job_id == job_id, JobScore.profile_id == profile_id)
            .order_by(JobScore.scoring_method)
        )
        return list(rows)

    async def counts(self, profile_id: uuid.UUID) -> dict[str, int]:
        rows = await self.session.execute(
            select(JobScore.scoring_method, func.count())
            .where(JobScore.profile_id == profile_id)
            .group_by(JobScore.scoring_method)
        )
        return {method: int(n) for method, n in rows}

    async def last_run(self) -> AgentRun | None:
        return await self.session.scalar(
            select(AgentRun)
            .where(AgentRun.agent_name == SCORING_AGENT)
            .order_by(AgentRun.started_at.desc())
            .limit(1)
        )
