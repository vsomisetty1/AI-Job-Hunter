"""Recommendations: what to change, from your history (pure).

Each recommendation comes from an insight that passed the statistical gates
(`insights.py`) or from a plain count over your records (e.g. how many of the
jobs you applied to asked for a skill missing from your profile). Each says
why, with the numbers, and links to where you can act. Nothing is changed for
you: settings, profile and applications stay under your control.
"""

from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from app.learning.dataset import Record
from app.learning.families import family_label
from app.learning.metrics import MIN_SAMPLE, overview

MIN_SKILL_ASKS = 5
MIN_SKILL_SHARE = 0.3
STALE_DAYS = 21


@dataclass
class Recommendation:
    key: str
    category: str  # targeting | profile | process | data
    priority: str  # high | medium | low
    title: str
    rationale: str
    action_label: str
    action_href: str
    based_on: list[str] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Context:
    profile_skills: frozenset[str] = frozenset()  # lower-case
    stale_scheduled: int = 0  # interviews still "scheduled" though their date has passed
    now: datetime | None = None


def recommend(
    records: list[Record], insights: list[dict[str, Any]], ctx: Context
) -> list[Recommendation]:
    now = ctx.now or datetime.now(UTC)
    ov = overview(records, now)
    out: list[Recommendation] = []
    out += _data_hygiene(records, ov, ctx, now)
    by_kind: dict[str, list[dict[str, Any]]] = {}
    for i in insights:
        by_kind.setdefault(i["kind"], []).append(i)

    for i in by_kind.get("threshold", []):
        t = int(i["segment"])
        below = [r for r in records if r.score is not None and r.score < t and not r.submitted]
        out.append(Recommendation(
            key=f"min-score:{t}", category="targeting", priority=_priority(i),
            title=f"Focus on jobs scoring {t} or more",
            rationale=f"{i['title']}: {i['detail']}"
            + (f" {len(below)} package(s) not yet sent score below {t}." if below else ""),
            action_label=f"Show jobs scoring {t}+", action_href=f"/jobs?min_score={t}",
            based_on=[i["key"]], evidence=i["evidence"],
        ))  # fmt: skip
    for i in by_kind.get("comparison", []):
        rec = _from_comparison(i)
        if rec is not None:
            out.append(rec)
    for i in by_kind.get("skill", []):
        if i["direction"] == "better":
            out.append(Recommendation(
                key=f"lead-skill:{i['segment']}".lower()[:200], category="profile",
                priority=_priority(i), title=f"Lead with {i['segment']} in your resume",
                rationale=f"{i['title']}: {i['detail']}",
                action_label="Edit your profile", action_href="/profile",
                based_on=[i["key"]], evidence=i["evidence"],
            ))  # fmt: skip
    out += _skill_gaps(records, ctx)
    seen, unique = set(), []
    for r in out:
        if r.key not in seen:
            seen.add(r.key)
            unique.append(r)
    order = {"high": 0, "medium": 1, "low": 2}
    return sorted(unique, key=lambda r: (order[r.priority], r.category, r.key))


def _priority(insight: dict[str, Any]) -> str:
    return {"high": "high", "medium": "medium"}.get(insight["confidence"], "low")


def _from_comparison(i: dict[str, Any]) -> Recommendation | None:
    dim, seg, better = i["dimension"], i["segment"], i["direction"] == "better"
    base = {"priority": _priority(i), "rationale": f"{i['title']}: {i['detail']}",
            "based_on": [i["key"]], "evidence": i["evidence"]}  # fmt: skip
    key = f"{dim}:{seg}:{'more' if better else 'less'}".lower().replace(" ", "-")[:200]
    if dim == "family":
        label = family_label(seg)
        return Recommendation(
            key=key, category="targeting",
            title=f"{'Target more' if better else 'Apply to fewer'} {label} roles",
            action_label="Search jobs", action_href=f"/jobs?q={label.split(' ')[0]}", **base,
        )  # fmt: skip
    if dim == "industry":
        return Recommendation(
            key=key, category="targeting",
            title=f"{'Focus on' if better else 'Deprioritise'} {seg} companies",
            action_label="Company insights", action_href="/insights/companies", **base,
        )  # fmt: skip
    if dim == "platform":
        return Recommendation(
            key=key, category="targeting",
            title=f"{'Track more' if better else 'Track fewer'} companies on {seg.capitalize()}",
            action_label="Manage companies", action_href="/discovery", **base,
        )  # fmt: skip
    if dim == "remote":
        word = {"remote": "remote", "hybrid": "hybrid", "onsite": "on-site"}.get(seg, seg)
        return Recommendation(
            key=key, category="targeting",
            title=f"{'Prefer' if better else 'Rely less on'} {word} roles",
            action_label="Job preferences", action_href="/settings", **base,
        )  # fmt: skip
    if dim == "cover_letter":
        with_letter = (seg == "with") == better
        return Recommendation(
            key=f"cover-letter:{'include' if with_letter else 'optional'}", category="process",
            title="Include a cover letter" if with_letter else "Cover letters did not help so far",
            action_label="Packages", action_href="/packages", **base,
        )  # fmt: skip
    if dim == "company":
        return Recommendation(
            key=key, category="targeting",
            title=f"{'Keep applying to' if better else 'Fewer applications to'} {seg}",
            action_label="Company insights", action_href="/insights/companies", **base,
        )  # fmt: skip
    if dim in ("resume_variant", "tailoring", "regenerated", "applied_via"):
        return Recommendation(
            key=key, category="process",
            title=f"{'Use more' if better else 'Use less'}: {i['title'].split(' got ')[0]}",
            action_label="Resume performance", action_href="/insights/resumes", **base,
        )  # fmt: skip
    return None


def _skill_gaps(records: list[Record], ctx: Context) -> list[Recommendation]:
    """Skills the jobs you applied to keep asking for that your profile lacks.
    A count, not a guess: phrased as "if you have it, add it"."""
    sent = [r for r in records if r.submitted or r.approved]
    if len(sent) < MIN_SAMPLE:
        return []
    counts = Counter(s for r in sent for s in set(r.missing_skills))
    out = []
    for skill, n in counts.most_common(5):
        if n < MIN_SKILL_ASKS or n / len(sent) < MIN_SKILL_SHARE:
            continue
        if skill.lower() in ctx.profile_skills:
            continue  # on the profile already (the job used another spelling)
        out.append(Recommendation(
            key=f"skill-gap:{skill}".lower().replace(" ", "-")[:200], category="profile",
            priority="medium",
            title=f"If you have {skill} experience, add it to your resume",
            rationale=(
                f"{n} of the {len(sent)} jobs you approved or applied to asked for {skill}, and "
                "your profile does not list it. Add it only if it is true."
            ),
            action_label="Edit your profile", action_href="/profile",
            evidence={"asked": n, "applications": len(sent)},
        ))  # fmt: skip
    return out


def _data_hygiene(
    records: list[Record], ov: dict[str, Any], ctx: Context, now: datetime
) -> list[Recommendation]:
    out = []
    unrecorded = [
        r for r in records
        if r.submitted and r.submitted_at and not r.responded and not r.withdrawn_at
        and now - r.submitted_at >= timedelta(days=STALE_DAYS)
    ]  # fmt: skip
    if unrecorded:
        out.append(Recommendation(
            key="data:record-outcomes", category="data", priority="high",
            title=f"Record outcomes for {len(unrecorded)} application(s)",
            rationale=(
                f"{len(unrecorded)} application(s) sent over {STALE_DAYS} days ago have no "
                "response recorded. If you heard back (even a rejection), record it: every "
                "rate and insight depends on it. If not, leave them: silence counts too."
            ),
            action_label="Interview pipeline", action_href="/insights/pipeline",
            evidence={"applications": len(unrecorded)},
        ))  # fmt: skip
    if ctx.stale_scheduled:
        out.append(Recommendation(
            key="data:update-scheduled", category="data", priority="high",
            title=f"Update {ctx.stale_scheduled} interview(s) still marked scheduled",
            rationale="Their date has passed. Mark each as completed, cancelled or no-show.",
            action_label="Interview pipeline", action_href="/insights/pipeline",
            evidence={"interviews": ctx.stale_scheduled},
        ))  # fmt: skip
    if ov["submitted"] < MIN_SAMPLE:
        out.append(Recommendation(
            key="data:more-history", category="data", priority="low",
            title="Keep applying and recording outcomes",
            rationale=(
                f"{ov['submitted']} of the {MIN_SAMPLE} submitted applications needed before "
                "comparisons are made. Until then, recommendations are limited to plain counts."
            ),
            action_label="Applications", action_href="/applications",
            evidence={"submitted": ov["submitted"], "needed": MIN_SAMPLE},
        ))  # fmt: skip
    with_industry = sum(1 for r in records if r.submitted and r.industry)
    if ov["submitted"] >= MIN_SAMPLE and with_industry < ov["submitted"] / 2:
        out.append(Recommendation(
            key="data:set-industries", category="data", priority="low",
            title="Set the industry of the companies you apply to",
            rationale=(
                f"Only {with_industry} of {ov['submitted']} submitted applications are at a "
                "company with an industry set, so industry comparisons cannot be made. The app "
                "never guesses industries."
            ),
            action_label="Company insights", action_href="/insights/companies",
            evidence={"with_industry": with_industry, "submitted": ov["submitted"]},
        ))  # fmt: skip
    return out
