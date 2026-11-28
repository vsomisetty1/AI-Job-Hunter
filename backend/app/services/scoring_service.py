"""Scoring: Agent 5's rule-based scores for every kept job, plus optional Claude
scores for a shortlist.

Rule-based (always, no tokens)
    Jobs that passed the filter and are still open are scored against the
    active profile in keyset pages, one short transaction per page. A job
    whose inputs hash (scorer version + job + profile + preferences) matches
    its stored score is skipped. New jobs move to status 'scored'.

Claude (optional)
    Runs only when the owner enabled it in settings AND an API key is set. It
    takes the best rule-scored jobs at or above `claude_scoring_min_score`
    that lack a current Claude score, and is bounded three ways:
    CLAUDE_SCORING_MAX_PER_RUN jobs per run, CLAUDE_SCORING_MAX_PER_DAY real
    API calls per rolling 24 hours (counted from agent_runs), and
    CLAUDE_SCORING_PER_MINUTE pacing. Answers are cached (app/llm/cache.py),
    and a cache hit costs nothing and is not paced. No transaction is open
    during a Claude call. A Claude score is tied to the rule-based inputs it
    saw (`input_hash`), so it stops counting as soon as those inputs change.
    Failures never touch the rule-based scores: an outage, rate limit or
    missing key stops the Claude pass; other errors skip that one job.
"""

import json
import logging
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.agent_5_job_scoring import (
    ScoringJob,
    ScoringPreferences,
    ScoringProfile,
    fingerprint,
    score,
)
from app.agents.runs import AgentRunHandle
from app.core.config import Settings
from app.llm.client import (
    ClaudeClient,
    LLMError,
    LLMNotConfiguredError,
    LLMResult,
    LLMTemporaryError,
)
from app.llm.prompts import JOB_SCORING
from app.llm.rate_limit import RateLimiter
from app.models.candidate_profile import CandidateProfile
from app.models.job import Job
from app.models.setting import Setting
from app.repositories.candidate_profile_repository import CandidateProfileRepository
from app.repositories.job_repository import JobRepository
from app.repositories.job_score_repository import (
    ClaudeCandidate,
    JobScoreRepository,
    ScoringCandidate,
)
from app.repositories.settings_repository import SettingsRepository
from app.schemas.job_score import ClaudeJobScoreOutput, ScoringSummary

logger = logging.getLogger(__name__)

PAGE_SIZE = 500
PROMPT_VERSION = f"{JOB_SCORING.name}:{JOB_SCORING.version}"
MAX_DESCRIPTION_CHARS = 8000
MAX_CONSECUTIVE_FAILURES = 3


def profile_input(p: CandidateProfile) -> ScoringProfile:
    return ScoringProfile(
        skills=tuple(p.skills),
        seniority=p.seniority,
        years_experience=float(p.years_experience) if p.years_experience is not None else None,
        roles=tuple(p.primary_roles),
        related_roles=tuple(p.related_roles),
        location=p.location,
    )


def preferences_input(s: Setting) -> ScoringPreferences:
    return ScoringPreferences(
        preferred_locations=tuple(s.preferred_locations),
        remote_preference=s.remote_preference,
        salary_min=s.salary_min,
        salary_target=s.salary_target,
        salary_currency=s.salary_currency,
    )


def job_input(c: ScoringCandidate | Job, company_name: str | None = None) -> ScoringJob:
    name = c.company_name if isinstance(c, ScoringCandidate) else company_name
    return ScoringJob(
        title=c.title,
        company_name=name or "",
        location=c.location,
        remote_type=c.remote_type,
        salary_min=c.salary_min,
        salary_max=c.salary_max,
        salary_currency=c.salary_currency,
        description=c.description,
        requirements=tuple(str(r) for r in c.requirements),
    )


def clamp(value: int) -> int:
    return max(0, min(100, int(value)))


@dataclass
class ClaudeOutcome:
    enabled: bool
    reason: str | None = None
    candidates: int = 0
    scored: int = 0
    calls: int = 0  # real API calls (what the daily cap counts)
    cached: int = 0
    failed: int = 0
    stopped: str | None = None
    errors: list[str] = field(default_factory=list)

    def as_json(self) -> dict[str, Any]:
        return self.__dict__.copy()


class ScoringService:
    def __init__(
        self,
        settings: Settings,
        llm: ClaudeClient,
        sessionmaker: async_sessionmaker[AsyncSession],
        limiter: RateLimiter | None = None,
    ) -> None:
        self.settings = settings
        self.llm = llm
        self.sessionmaker = sessionmaker
        self.limiter = limiter or RateLimiter(settings.claude_scoring_per_minute)

    # ------------------------------------------------------------------ run
    async def run(self, run: AgentRunHandle | None = None) -> dict[str, Any]:
        async with self.sessionmaker() as session, session.begin():
            profile = await CandidateProfileRepository(session).get_active()
            user_settings = await SettingsRepository(session).get_singleton()
            profile_id = profile.id if profile else None
            prof = profile_input(profile) if profile else None
            prefs = preferences_input(user_settings)
            claude_wanted = user_settings.claude_scoring_enabled
            min_score = user_settings.claude_scoring_min_score
        if profile_id is None or prof is None:
            logger.info("scoring skipped: no profile yet")
            return {"skipped": True, "reason": "no_profile"}

        rules = await self.score_rules(profile_id, prof, prefs)
        claude = await self.score_claude(
            profile_id, prof, prefs, wanted=claude_wanted, min_score=min_score, run=run
        )
        return {"profile_id": str(profile_id), "rules": rules, "claude": claude.as_json()}

    # ----------------------------------------------------------- rule-based
    async def score_rules(
        self, profile_id: uuid.UUID, prof: ScoringProfile, prefs: ScoringPreferences
    ) -> dict[str, int]:
        counts: Counter[str] = Counter()
        after = None
        while True:
            async with self.sessionmaker() as session, session.begin():
                repo = JobScoreRepository(session)
                page = await repo.rules_candidates(profile_id, after=after, limit=PAGE_SIZE)
                if not page:
                    break
                rows, new_ids = [], []
                for c in page:
                    job = job_input(c)
                    digest = fingerprint(job, prof, prefs)
                    if c.status == "new":
                        new_ids.append(c.job_id)
                    if digest == c.rules_hash:
                        counts["unchanged"] += 1
                        continue
                    result = score(job, prof, prefs)
                    rows.append(
                        {
                            "job_id": c.job_id,
                            "profile_id": profile_id,
                            "scoring_method": "rules",
                            "overall_score": result.overall,
                            "skills_score": result.component_score("skills"),
                            "seniority_score": result.component_score("seniority"),
                            "location_score": result.component_score("location"),
                            "relevance_score": result.component_score("relevance"),
                            "salary_score": result.component_score("salary"),
                            "rationale": result.rationale,
                            "matched_skills": result.matched_skills,
                            "missing_skills": result.missing_skills,
                            "breakdown": result.breakdown(),
                            "input_hash": digest,
                        }
                    )
                await repo.upsert(rows)
                await repo.mark_scored(new_ids)
                counts["scored"] += len(rows)
                counts["evaluated"] += len(page)
                after = page[-1].job_id
        summary = {
            "evaluated": counts["evaluated"],
            "scored": counts["scored"],
            "unchanged": counts["unchanged"],
        }
        logger.info("rule-based scoring: %s scored, %s unchanged", summary["scored"],
                    summary["unchanged"])  # fmt: skip
        return summary

    # -------------------------------------------------------------- status
    async def summary(self, *, task_running: bool) -> ScoringSummary:
        async with self.sessionmaker() as session:
            profile = await CandidateProfileRepository(session).get_active()
            user_settings = await SettingsRepository(session).get_singleton()
            jobs = await JobRepository(session).filter_counts()
            scores_repo = JobScoreRepository(session)
            by_method = await scores_repo.counts(profile.id) if profile else {}
            last = await scores_repo.last_run()
            since = datetime.now(UTC) - timedelta(days=1)
            calls = await scores_repo.claude_calls_since(since)
        return ScoringSummary(
            profile_id=profile.id if profile else None,
            jobs_active=jobs["active"],
            jobs_unfiltered=jobs["unfiltered"],
            jobs_passed=jobs["passed"],
            jobs_rejected=jobs["rejected"],
            jobs_duplicate=jobs["duplicate"],
            jobs_scored=by_method.get("rules", 0),
            jobs_claude_scored=by_method.get("claude", 0),
            claude_available=self.llm.enabled,
            claude_enabled=user_settings.claude_scoring_enabled,
            claude_calls_today=calls,
            claude_daily_limit=self.settings.claude_scoring_max_per_day,
            last_run_at=last.started_at if last else None,
            last_run_status=last.status if last else None,
            task_running=task_running,
        )

    # --------------------------------------------------------------- Claude
    async def calls_today(self) -> int:
        since = datetime.now(UTC) - timedelta(days=1)
        async with self.sessionmaker() as session:
            return await JobScoreRepository(session).claude_calls_since(since)

    async def score_claude(
        self,
        profile_id: uuid.UUID,
        prof: ScoringProfile,
        prefs: ScoringPreferences,
        *,
        wanted: bool,
        min_score: int,
        run: AgentRunHandle | None = None,
    ) -> ClaudeOutcome:
        if not wanted:
            return ClaudeOutcome(enabled=False, reason="disabled in settings")
        if not self.llm.enabled:
            return ClaudeOutcome(enabled=False, reason="no ANTHROPIC_API_KEY configured")
        budget = min(
            self.settings.claude_scoring_max_per_run,
            self.settings.claude_scoring_max_per_day - await self.calls_today(),
        )
        outcome = ClaudeOutcome(enabled=True)
        if budget <= 0:
            outcome.stopped = "daily or per-run limit reached"
            return outcome
        async with self.sessionmaker() as session:
            candidates = await JobScoreRepository(session).claude_candidates(
                profile_id, min_score=min_score, prompt_version=PROMPT_VERSION, limit=budget
            )
        outcome.candidates = len(candidates)

        failures_in_a_row = 0
        for cand in candidates:
            # Cache hits are free and do not count towards the caps.
            if outcome.calls >= budget:
                outcome.stopped = "daily or per-run limit reached"
                break
            try:
                result = await self._ask(cand, prof, prefs)
            except (LLMNotConfiguredError, LLMTemporaryError) as exc:
                outcome.stopped = exc.message
                outcome.errors.append(exc.message)
                break
            except LLMError as exc:
                outcome.failed += 1
                outcome.errors.append(exc.message)
                failures_in_a_row += 1
                if failures_in_a_row >= MAX_CONSECUTIVE_FAILURES:
                    outcome.stopped = f"{failures_in_a_row} failures in a row"
                    break
                continue
            if result is None:  # job disappeared or changed meanwhile
                continue
            failures_in_a_row = 0
            if result.cached:
                outcome.cached += 1
            else:
                outcome.calls += 1
                if run is not None:
                    u = result.usage
                    run.add_usage(u.input_tokens, u.output_tokens, u.cost_usd)
            await self._save_claude(profile_id, cand, result)
            outcome.scored += 1
        logger.info(
            "claude scoring: %s scored (%s calls, %s cached, %s failed)",
            outcome.scored, outcome.calls, outcome.cached, outcome.failed,
        )  # fmt: skip
        return outcome

    async def _ask(
        self, cand: ClaudeCandidate, prof: ScoringProfile, prefs: ScoringPreferences
    ) -> LLMResult[ClaudeJobScoreOutput] | None:
        async with self.sessionmaker() as session:
            row = await JobRepository(session).get_with_company(cand.job_id)
        if row is None:
            return None
        job, company_name, _ = row
        if fingerprint(job_input(job, company_name), prof, prefs) != cand.rules_hash:
            return None  # inputs changed after the rule pass; the next run handles it
        return await self.llm.structured(
            JOB_SCORING,
            model=self.settings.claude_model_scoring,
            effort=self.settings.claude_effort_scoring,
            limiter=self.limiter,
            candidate_json=_dumps(
                {
                    "seniority": prof.seniority,
                    "years_experience": prof.years_experience,
                    "skills": list(prof.skills),
                    "target_roles": list(prof.roles),
                    "related_roles": list(prof.related_roles),
                }
            ),
            preferences_json=_dumps(
                {
                    "preferred_locations": list(prefs.preferred_locations),
                    "remote_preference": prefs.remote_preference,
                    "salary_target": prefs.salary_target or prefs.salary_min,
                    "salary_currency": prefs.salary_currency,
                }
            ),
            rules_json=_dumps(
                {
                    "overall": cand.rules_overall,
                    "components": {
                        name: {"score": c.get("score"), "summary": c.get("summary")}
                        for name, c in cand.rules_breakdown.get("components", {}).items()
                    },
                    "matched_skills": cand.matched_skills,
                    "missing_skills": cand.missing_skills,
                }
            ),
            job_json=_dumps(
                {
                    "title": job.title,
                    "company": company_name,
                    "location": job.location,
                    "workplace": job.remote_type,
                    "employment_type": job.employment_type,
                    "salary_min": job.salary_min,
                    "salary_max": job.salary_max,
                    "salary_currency": job.salary_currency,
                    "compensation": job.compensation_text,
                    "requirements": list(job.requirements),
                    "description": job.description[:MAX_DESCRIPTION_CHARS],
                }
            ),
        )

    async def _save_claude(
        self,
        profile_id: uuid.UUID,
        cand: ClaudeCandidate,
        result: LLMResult[ClaudeJobScoreOutput],
    ) -> None:
        out, usage = result.output, result.usage
        row = {
            "job_id": cand.job_id,
            "profile_id": profile_id,
            "scoring_method": "claude",
            "overall_score": clamp(out.overall_score),
            "skills_score": clamp(out.skills_score),
            "seniority_score": clamp(out.seniority_score),
            "location_score": None,
            "relevance_score": None,
            "salary_score": None,
            "interview_probability": clamp(out.interview_probability),
            "growth_score": clamp(out.growth_score),
            "company_score": clamp(out.company_score),
            "rationale": out.rationale,
            "matched_skills": out.matched_skills,
            "missing_skills": out.missing_skills,
            "breakdown": {
                "strengths": out.strengths,
                "concerns": out.concerns,
                "rules_overall": cand.rules_overall,
                "cached": result.cached,
            },
            "input_hash": cand.rules_hash,
            "model": usage.model,
            "prompt_version": PROMPT_VERSION,
            "input_tokens": 0 if result.cached else usage.input_tokens,
            "output_tokens": 0 if result.cached else usage.output_tokens,
        }
        async with self.sessionmaker() as session, session.begin():
            await JobScoreRepository(session).upsert([row])


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)
