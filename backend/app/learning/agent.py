"""Learning Agent: analyses applications, interviews, offers and rejections and
stores a snapshot of what it learned (metrics, insights, recommendations).

Runs daily (scheduler) and on demand ("Refresh"). Analysis is deterministic
and uses only your recorded data (see insights.py for the gates). A snapshot
is stored only when the inputs changed since the last one, so the history is
a trend of real changes.
"""

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.runs import track_agent_run
from app.learning import insights as insights_engine
from app.learning.dataset import Record, data_hash, load_records
from app.learning.metrics import funnel, overview, score_accuracy
from app.learning.recommendations import Context, recommend
from app.models.candidate_profile import CandidateProfile
from app.models.learning import InterviewEvent, LearningSnapshot

logger = logging.getLogger(__name__)


async def context(session: AsyncSession, now: datetime) -> Context:
    profile = await session.scalar(
        select(CandidateProfile).where(CandidateProfile.is_active.is_(True)).limit(1)
    )
    stale = await session.scalar(
        select(func.count())
        .select_from(InterviewEvent)
        .where(
            InterviewEvent.status == "scheduled",
            InterviewEvent.occurred_at < now - timedelta(days=1),
        )
    )  # fmt: skip
    skills = frozenset(s.lower() for s in (profile.skills if profile else []))
    return Context(profile_skills=skills, stale_scheduled=int(stale or 0), now=now)


def analyse(records: list[Record], ctx: Context) -> dict[str, Any]:
    now = ctx.now or datetime.now(UTC)
    report = insights_engine.generate(records, now)
    recs = recommend(records, report["insights"], ctx)
    return {
        "summary": {
            "overview": overview(records, now),
            "funnel": funnel(records),
            "score_accuracy": score_accuracy(records),
        },
        "insights": report,
        "recommendations": [r.as_dict() for r in recs],
    }


class LearningAgent:
    name = "learning_agent"

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self.sessionmaker = sessionmaker

    async def run(self, trigger: str = "manual") -> dict[str, Any]:
        now = datetime.now(UTC)
        async with track_agent_run(
            self.name, input_summary={"trigger": trigger}, sessionmaker=self.sessionmaker
        ) as run:
            async with self.sessionmaker() as session:
                records = await load_records(session)
                ctx = await context(session, now)
            result = analyse(records, ctx)
            digest = data_hash(records)
            async with self.sessionmaker() as session, session.begin():
                last = await session.scalar(
                    select(LearningSnapshot).order_by(LearningSnapshot.created_at.desc()).limit(1)
                )
                stored = last is None or last.data_hash != digest
                if stored:
                    session.add(
                        LearningSnapshot(
                            data_hash=digest,
                            summary=result["summary"],
                            insights=result["insights"]["insights"],
                            recommendations=result["recommendations"],
                        )
                    )
            ov = result["summary"]["overview"]
            run.output_summary.update(
                {
                    "records": len(records),
                    "submitted": ov["submitted"],
                    "insights": len(result["insights"]["insights"]),
                    "recommendations": len(result["recommendations"]),
                    "stored": stored,
                }  # fmt: skip
            )
        logger.info("learning agent finished", extra={"stored": stored, "records": len(records)})
        return {"stored": stored, "records": len(records), "computed_at": now.isoformat()}
