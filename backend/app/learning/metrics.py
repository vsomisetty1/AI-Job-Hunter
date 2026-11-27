"""Metrics over the learning dataset (pure functions).

Definitions (rates are over SUBMITTED applications):
* response rate: any reply from the employer (a recruiter response, a scheduled
  or held screen or interview, an offer or a rejection);
* interview rate: at least one screen or interview round was scheduled or held;
* offer rate: an offer was received;
* conversion: each funnel step over the step before it
  (package generated -> approved -> submitted -> response -> interview -> offer).
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from app.learning.dataset import Record
from app.learning.families import family_label
from app.learning.stats import Rate, auc, auc_p_value, fisher_exact, median

MIN_SAMPLE = 10  # submitted applications before outcome-based analysis means anything
MIN_SEGMENT = 5  # submitted applications per group before two groups are compared
AWAITING_DAYS = 14  # a reply usually comes within two weeks, or not at all
SCORE_BANDS = ((0, 59, "below 60"), (60, 69, "60-69"), (70, 79, "70-79"), (80, 84, "80-84"),
               (85, 100, "85+"))  # fmt: skip
OUTCOMES = ("responded", "interviewed", "offered")
OUTCOME_LABEL = {"responded": "a response", "interviewed": "an interview", "offered": "an offer"}


@dataclass
class Segment:
    key: str
    label: str
    packages: int = 0
    submitted: int = 0
    responded: int = 0
    interviewed: int = 0
    offered: int = 0
    rejected: int = 0
    days_to_response: list[float] | None = None

    def rate(self, outcome: str) -> Rate:
        return Rate(getattr(self, outcome), self.submitted)

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "packages": self.packages,
            "submitted": self.submitted,
            "responded": self.responded,
            "interviewed": self.interviewed,
            "offered": self.offered,
            "rejected": self.rejected,
            "response_rate": self.rate("responded").as_dict(),
            "interview_rate": self.rate("interviewed").as_dict(),
            "offer_rate": self.rate("offered").as_dict(),
            "median_days_to_response": median(self.days_to_response or []),
        }


def segments(
    records: list[Record],
    key: Callable[[Record], str | None],
    label: Callable[[str], str] = lambda k: k,
) -> list[Segment]:
    """Group records; records whose key is None are left out."""
    groups: dict[str, Segment] = {}
    for r in records:
        k = key(r)
        if k is None:
            continue
        seg = groups.setdefault(k, Segment(k, label(k), days_to_response=[]))
        seg.packages += 1
        if not r.submitted:
            continue
        seg.submitted += 1
        seg.responded += r.responded
        seg.interviewed += r.interviewed
        seg.offered += r.offered
        seg.rejected += r.rejected
        if r.responded and r.submitted_at and r.responded_at and seg.days_to_response is not None:
            seg.days_to_response.append(
                max(0.0, (r.responded_at - r.submitted_at).total_seconds() / 86400)
            )
    return sorted(groups.values(), key=lambda s: (-s.submitted, -s.packages, s.label))


def total(records: list[Record]) -> Segment:
    return segments(records, lambda _r: "all", lambda _k: "All applications")[0] if records else (
        Segment("all", "All applications", days_to_response=[]))  # fmt: skip


# ---------------------------------------------------------------- overview
def funnel(records: list[Record]) -> list[dict[str, Any]]:
    steps = (
        ("generated", "Package generated", len(records)),
        ("approved", "Package approved", sum(r.approved for r in records)),
        ("submitted", "Application submitted", sum(r.submitted for r in records)),
        ("responded", "Employer responded", sum(r.responded for r in records if r.submitted)),
        ("interviewed", "Interview received", sum(r.interviewed for r in records if r.submitted)),
        ("offered", "Offer received", sum(r.offered for r in records if r.submitted)),
    )
    out = []
    previous: int | None = None
    start = steps[0][2]
    for key, label, count in steps:
        out.append({
            "stage": key, "label": label, "count": count,
            "from_previous": Rate(count, previous).as_dict() if previous else None,
            "from_start": Rate(count, start).as_dict() if start else None,
        })  # fmt: skip
        previous = count
    return out


def overview(records: list[Record], now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    t = total(records)
    sent = [r for r in records if r.submitted]
    awaiting = [
        r for r in sent
        if not r.responded and not r.withdrawn_at and r.submitted_at
        and now - r.submitted_at < timedelta(days=AWAITING_DAYS)
    ]  # fmt: skip
    silent = [
        r for r in sent
        if not r.responded and not r.withdrawn_at and r.submitted_at
        and now - r.submitted_at >= timedelta(days=AWAITING_DAYS)
    ]  # fmt: skip
    return {
        "packages": len(records),
        "approved": sum(r.approved for r in records),
        "submitted": t.submitted,
        "responded": t.responded,
        "interviewed": t.interviewed,
        "offered": t.offered,
        "rejected": t.rejected,
        "withdrawn": sum(r.withdrawn_at is not None for r in sent),
        "awaiting_reply": len(awaiting),
        "no_reply_after_14_days": len(silent),
        "response_rate": t.rate("responded").as_dict(),
        "interview_rate": t.rate("interviewed").as_dict(),
        "offer_rate": t.rate("offered").as_dict(),
        "approval_rate": Rate(sum(r.approved for r in records), len(records)).as_dict(),
        "submission_rate": Rate(t.submitted, sum(r.approved for r in records)).as_dict(),
        "interview_to_offer": Rate(t.offered, t.interviewed).as_dict(),
        "median_days_to_response": median(t.days_to_response or []),
        "enough_data": t.submitted >= MIN_SAMPLE,
        "min_sample": MIN_SAMPLE,
    }


# ---------------------------------------------------------- score accuracy
def score_band(score: int | None) -> str | None:
    if score is None:
        return None
    return next(label for lo, hi, label in SCORE_BANDS if lo <= score <= hi)


def score_accuracy(records: list[Record]) -> dict[str, Any]:
    """How well the job score predicted what happened (submitted, scored jobs)."""
    scored = [r for r in records if r.submitted and r.score is not None]
    order = [label for *_, label in SCORE_BANDS]
    bands = sorted(segments(scored, lambda r: score_band(r.score)),
                   key=lambda s: order.index(s.key))  # fmt: skip
    result: dict[str, Any] = {"scored_submitted": len(scored),
                              "bands": [b.as_dict() for b in bands]}  # fmt: skip
    for outcome in ("interviewed", "responded"):
        pos = [float(r.score) for r in scored if getattr(r, outcome) and r.score is not None]
        neg = [float(r.score) for r in scored if not getattr(r, outcome) and r.score is not None]
        value = auc(pos, neg)
        p = auc_p_value(pos, neg)
        spread = (max(pos + neg) - min(pos + neg)) if pos and neg else 0.0
        result[outcome] = {
            "auc": round(value, 3) if value is not None else None,
            "p_value": round(p, 4) if p is not None else None,
            "score_spread": spread,
            "positives": len(pos),
            "negatives": len(neg),
            "mean_score_positive": round(sum(pos) / len(pos), 1) if pos else None,
            "mean_score_negative": round(sum(neg) / len(neg), 1) if neg else None,
            "enough_data": len(pos) >= 3 and len(neg) >= 3 and len(scored) >= MIN_SAMPLE,
            "verdict": _verdict(value, p, spread, len(pos), len(neg), len(scored)),
        }
    return result


MIN_SCORE_SPREAD = 10  # points between the lowest and highest score
MAX_AUC_P = 0.10


def _verdict(
    value: float | None, p: float | None, spread: float, pos: int, neg: int, n: int
) -> str:
    """A verdict only when the scores vary enough and the relation is unlikely
    to be chance; otherwise say so."""
    if value is None or p is None or pos < 3 or neg < 3 or n < MIN_SAMPLE:
        return "not enough outcomes yet"
    if spread < MIN_SCORE_SPREAD:
        return "scores are too similar to judge"
    if p > MAX_AUC_P:
        return "no clear relationship yet"
    if value >= 0.7:
        return "scores predict outcomes well"
    if value >= 0.6:
        return "scores predict outcomes somewhat"
    if value > 0.45:
        return "scores do not predict outcomes yet"
    return "higher scores did worse: review the scoring weights"


# ------------------------------------------------------- skill correlations
def skill_correlations(records: list[Record], min_support: int = 4) -> list[dict[str, Any]]:
    """For each skill the jobs asked for: interview rate when you had it (it was
    matched) vs when you did not (it was missing). Submitted applications only."""
    sent = [r for r in records if r.submitted]
    asked: dict[str, dict[str, list[Record]]] = {}
    for r in sent:
        for s in r.matched_skills:
            asked.setdefault(s, {"have": [], "lack": []})["have"].append(r)
        for s in r.missing_skills:
            asked.setdefault(s, {"have": [], "lack": []})["lack"].append(r)
    out = []
    for skill, groups in asked.items():
        have, lack = groups["have"], groups["lack"]
        if len(have) + len(lack) < min_support:
            continue
        h = Rate(sum(r.interviewed for r in have), len(have))
        lk = Rate(sum(r.interviewed for r in lack), len(lack))
        p = fisher_exact(h.k, h.n - h.k, lk.k, lk.n - lk.k) if have and lack else None
        out.append({
            "skill": skill,
            "asked": len(have) + len(lack),
            "have": h.as_dict(),
            "lack": lk.as_dict(),
            "lift": round(h.value / lk.value, 2) if h.value and lk.value else None,
            "p_value": round(p, 4) if p is not None else None,
        })  # fmt: skip
    return sorted(out, key=lambda x: (-int(x["asked"]), str(x["skill"])))


# --------------------------------------------------------------- dimensions
def regenerated(r: Record) -> str:
    return "regenerated" if r.package_versions > 1 else "first version"


DIMENSIONS: dict[str, dict[str, Any]] = {
    "company": {"key": lambda r: r.company, "label": lambda k: k,
                "noun": "Applications to {label}", "rest": "other companies"},
    "platform": {"key": lambda r: r.platform, "label": lambda k: k.capitalize(),
                 "noun": "{label} jobs", "rest": "jobs on other boards"},
    "industry": {"key": lambda r: r.industry, "label": lambda k: k,
                 "noun": "{label} companies", "rest": "companies in other industries"},
    "family": {"key": lambda r: r.family, "label": family_label,
               "noun": "{label} roles", "rest": "other roles"},
    "remote": {"key": lambda r: r.remote_type if r.remote_type != "unknown" else None,
               "label": lambda k: {"remote": "Remote", "hybrid": "Hybrid", "onsite": "On-site"}
               .get(k, k), "noun": "{label} jobs", "rest": "other jobs"},
    "cover_letter": {"key": lambda r: "with" if r.cover_letter else "without",
                     "label": lambda k: f"{k} a cover letter",
                     "noun": "Applications {label}", "rest": "the others"},
    "tailoring": {"key": lambda r: r.tailoring_method, "label": lambda k: {
                  "claude": "reworded by Claude", "rules": "tailored by rules"}.get(k, k),
                  "noun": "Resumes {label}", "rest": "the others"},
    "resume_variant": {"key": lambda r: r.resume_variant, "label": lambda k: k,
                       "noun": "Packages built from {label}", "rest": "other resume versions"},
    "regenerated": {"key": regenerated, "label": lambda k: k,
                    "noun": "Packages ({label})", "rest": "the others"},
    "applied_via": {"key": lambda r: r.applied_via, "label": lambda k: {
                    "automation": "filled by the app", "manual": "applied by hand"}.get(k, k),
                    "noun": "Applications {label}", "rest": "the others"},
}  # fmt: skip


def dimension(records: list[Record], name: str) -> list[Segment]:
    d = DIMENSIONS[name]
    return segments(records, d["key"], d["label"])
