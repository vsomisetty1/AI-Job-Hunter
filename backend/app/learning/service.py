"""Analytics, insights and recommendations for the API.

Everything is computed live from your records (fast at personal scale), so the
pages always reflect the latest outcome you recorded. The Learning Agent's
snapshots give the history.
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.exceptions import NotFoundError
from app.learning import insights as insights_engine
from app.learning.agent import LearningAgent, analyse, context
from app.learning.dataset import Record, load_records
from app.learning.families import family_label
from app.learning.metrics import (
    dimension,
    funnel,
    overview,
    score_accuracy,
    segments,
    skill_correlations,
)
from app.models.company import Company
from app.models.learning import LearningSnapshot, RecommendationState

STYLE_DIMENSIONS = ("resume_variant", "tailoring", "cover_letter", "regenerated", "applied_via")


class LearningService:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self.sessionmaker = sessionmaker
        self.agent = LearningAgent(sessionmaker)

    async def _records(self) -> list[Record]:
        async with self.sessionmaker() as session:
            return await load_records(session)

    # --------------------------------------------------------- dashboard
    async def summary(self) -> dict[str, Any]:
        records = await self._records()
        now = datetime.now(UTC)
        return {
            "computed_at": now.isoformat(),
            "overview": overview(records, now),
            "funnel": funnel(records),
            "score_accuracy": score_accuracy(records),
            "skill_correlations": skill_correlations(records)[:30],
            "by_family": [
                s.as_dict() for s in segments(records, lambda r: r.family, family_label)
            ],  # fmt: skip
            "by_remote": [s.as_dict() for s in dimension(records, "remote")],
            "by_score_band": score_accuracy(records)["bands"],
        }

    async def companies(self) -> list[dict[str, Any]]:
        records = await self._records()
        segs = {s.key: s for s in segments(records, lambda r: r.company_id)}
        async with self.sessionmaker() as session:
            companies = {
                str(c.id): c
                for c in await session.scalars(select(Company).where(Company.id.in_(
                    [c for c in segs])))  # fmt: skip
            } if segs else {}  # fmt: skip
        out = []
        for key, seg in segs.items():
            c = companies.get(key)
            row = seg.as_dict()
            row.update(
                company_id=key, label=c.name if c else key, industry=c.industry if c else None,
                platform=c.source if c else None,
            )  # fmt: skip
            out.append(row)
        return out

    async def boards(self) -> list[dict[str, Any]]:
        records = await self._records()
        out = []
        for seg in dimension(records, "platform"):
            subset = [r for r in records if r.platform == seg.key]
            row = seg.as_dict()
            row["funnel"] = funnel(subset)
            out.append(row)
        return out

    async def resumes(self) -> dict[str, Any]:
        records = await self._records()
        return {
            name: [s.as_dict() for s in dimension(records, name)]
            for name in STYLE_DIMENSIONS
        } | {
            "cover_letter_method": [s.as_dict() for s in segments(
                [r for r in records if r.cover_letter], lambda r: r.cover_letter_method)],
        }  # fmt: skip

    async def insights(self) -> dict[str, Any]:
        return insights_engine.generate(await self._records())

    # ---------------------------------------------------- recommendations
    async def recommendations(self, include_dismissed: bool = False) -> list[dict[str, Any]]:
        now = datetime.now(UTC)
        async with self.sessionmaker() as session:
            records = await load_records(session)
            ctx = await context(session, now)
            states = {s.key: s for s in await session.scalars(select(RecommendationState))}
        out = []
        for rec in analyse(records, ctx)["recommendations"]:
            state = states.get(rec["key"])
            rec["state"] = state.status if state else None
            if state is None or include_dismissed:
                out.append(rec)
        return out

    async def set_state(self, key: str, status: str | None, note: str | None) -> dict[str, Any]:
        async with self.sessionmaker() as session, session.begin():
            row = await session.get(RecommendationState, key)
            if status is None:
                if row is None:
                    raise NotFoundError("No state for this recommendation", {"key": key})
                await session.delete(row)
                return {"key": key, "state": None}
            if row is None:
                row = RecommendationState(key=key, status=status, note=note)
                session.add(row)
            else:
                row.status, row.note, row.updated_at = status, note, datetime.now(UTC)
        return {"key": key, "state": status}

    # ------------------------------------------------------------ history
    async def history(self, limit: int = 90) -> list[dict[str, Any]]:
        async with self.sessionmaker() as session:
            rows = list(
                await session.scalars(
                    select(LearningSnapshot).order_by(LearningSnapshot.created_at.desc()).limit(limit)
                )
            )  # fmt: skip
        points = []
        for s in reversed(rows):
            ov = s.summary.get("overview", {})
            points.append({
                "at": s.created_at.isoformat(),
                "submitted": ov.get("submitted"),
                "response_rate": (ov.get("response_rate") or {}).get("rate"),
                "interview_rate": (ov.get("interview_rate") or {}).get("rate"),
                "offer_rate": (ov.get("offer_rate") or {}).get("rate"),
                "insights": len(s.insights),
                "recommendations": len(s.recommendations),
            })  # fmt: skip
        return points

    async def refresh(self, trigger: str = "manual") -> dict[str, Any]:
        return await self.agent.run(trigger)
