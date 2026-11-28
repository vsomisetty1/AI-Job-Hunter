"""Insights: statements about YOUR applications, only when the data supports them.

An insight is generated from your records and nothing else, and only when:
* each compared group has at least MIN_SEGMENT submitted applications;
* the outcome happened at least 3 times and failed to happen at least 3 times
  overall (otherwise there is nothing to learn);
* the difference is at least 10 percentage points and 1.5x;
* Fisher's exact test, Holm-corrected for every comparison made in the same
  family (dimension x outcome), gives p <= MAX_P.
Every insight carries its counts, the test, and the number of comparisons
made, so a reader can judge it. Facts (medians, counts) need fewer conditions
but still come only from recorded data. With too little data the engine says
so instead of guessing.
"""

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.learning.dataset import Record
from app.learning.metrics import (
    DIMENSIONS,
    MIN_SAMPLE,
    MIN_SEGMENT,
    OUTCOME_LABEL,
    OUTCOMES,
    dimension,
    overview,
    score_accuracy,
    skill_correlations,
)
from app.learning.stats import Rate, confidence, fisher_exact, holm

MAX_P = 0.10
MIN_DIFF = 0.10
MIN_RATIO = 1.5
SCORE_THRESHOLDS = (70, 75, 80, 85, 90)


@dataclass
class Insight:
    key: str
    kind: str  # comparison | threshold | skill | score | fact
    title: str
    detail: str
    confidence: str  # high | medium | low | fact
    direction: str = "neutral"  # better | worse | neutral
    dimension: str | None = None
    segment: str | None = None
    outcome: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class _Candidate:
    dimension: str
    segment: str
    label: str
    rest: str
    outcome: str
    a: Rate
    b: Rate
    p: float


def pct(rate: Rate) -> str:
    return f"{round(100 * rate.value)}%" if rate.value is not None else "n/a"


def generate(records: list[Record], now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    ov = overview(records, now)
    insights: list[Insight] = _facts(records, ov)
    tested = 0
    if ov["submitted"] < MIN_SAMPLE:
        return {
            "status": "insufficient_data",
            "message": (
                f"{ov['submitted']} submitted application(s) so far. Comparisons start at "
                f"{MIN_SAMPLE}, with outcomes recorded for them; until then only plain facts "
                "are shown."
            ),
            "comparisons_tested": 0,
            "insights": [i.as_dict() for i in insights],
        }
    for name in DIMENSIONS:
        found, n = _compare_dimension(records, name)
        insights += found
        tested += n
    found, n = _score_threshold(records)
    insights += found
    tested += n
    found, n = _skills(records)
    insights += found
    tested += n
    rank = {"high": 0, "medium": 1, "low": 2, "fact": 3}
    insights.sort(key=lambda i: (rank[i.confidence], i.kind == "fact", i.key))
    return {
        "status": "ok",
        "message": f"{len(insights)} insight(s) from {ov['submitted']} submitted applications; "
        f"{tested} comparisons were tested and only those that held up are shown.",
        "comparisons_tested": tested,
        "insights": [i.as_dict() for i in insights],
    }


def _usable(outcome: str, k: int, n: int) -> bool:
    return k >= 3 and n - k >= 3


def _compare_dimension(records: list[Record], name: str) -> tuple[list[Insight], int]:
    spec = DIMENSIONS[name]
    segs = [s for s in dimension(records, name) if s.submitted >= MIN_SEGMENT]
    out: list[Insight] = []
    tested = 0
    for outcome in OUTCOMES:
        cands: list[_Candidate] = []
        all_segs = dimension(records, name)
        k_all = sum(getattr(s, outcome) for s in all_segs)
        n_all = sum(s.submitted for s in all_segs)
        if not _usable(outcome, k_all, n_all):
            continue
        two = len(all_segs) == 2
        for s in segs:
            rest_n = n_all - s.submitted
            rest_k = k_all - getattr(s, outcome)
            if rest_n < MIN_SEGMENT:
                continue
            a, b = Rate(getattr(s, outcome), s.submitted), Rate(rest_k, rest_n)
            p = fisher_exact(a.k, a.n - a.k, b.k, b.n - b.k)
            rest = spec["rest"] if not two else spec["noun"].format(
                label=next(x.label for x in all_segs if x.key != s.key)).lower()  # fmt: skip
            cands.append(_Candidate(name, s.key, s.label, rest, outcome, a, b, p))
            if two:
                break  # A vs B is one comparison, not two
        tested += len(cands)
        for cand, p_adj in zip(cands, holm([c.p for c in cands]), strict=True):
            insight = _comparison(spec["noun"].format(label=cand.label), cand, p_adj, len(cands))
            if insight is not None:
                out.append(insight)
    return out, tested


def _comparison(noun: str, c: _Candidate, p_adj: float, m: int) -> Insight | None:
    va, vb = c.a.value or 0.0, c.b.value or 0.0
    diff = va - vb
    if p_adj > MAX_P or abs(diff) < MIN_DIFF:
        return None
    ratio = va / vb if vb else None
    if ratio is not None and 1 / MIN_RATIO < ratio < MIN_RATIO:
        return None
    what = OUTCOME_LABEL[c.outcome]
    if diff > 0:
        how = f"{ratio:.1f}x as often as" if ratio else "more often than"
        title = f"{noun} got {what} {how} {c.rest}"
    else:
        how = f"{1 / ratio:.1f}x less often than" if ratio else "less often than"
        title = f"{noun} got {what} {how} {c.rest}"
    detail = (
        f"{c.a.k} of {c.a.n} ({pct(c.a)}) vs {c.b.k} of {c.b.n} ({pct(c.b)}) for {c.rest}. "
        f"Fisher exact p = {c.p:.3f}; {p_adj:.3f} after correcting for {m} comparison(s)."
    )
    return Insight(
        key=f"{c.dimension}:{c.segment}:{c.outcome}".lower().replace(" ", "-")[:200],
        kind="comparison",
        title=title,
        detail=detail,
        confidence=confidence(p_adj),
        direction="better" if diff > 0 else "worse",
        dimension=c.dimension,
        segment=c.segment,
        outcome=c.outcome,
        evidence={
            "group": c.a.as_dict(),
            "rest": c.b.as_dict(),
            "p_value": round(c.p, 4),
            "p_adjusted": round(p_adj, 4),
            "comparisons": m,
        },  # fmt: skip
    )


def _score_threshold(records: list[Record]) -> tuple[list[Insight], int]:
    """Do jobs above a score threshold convert better? One insight per outcome,
    for the threshold with the strongest evidence."""
    sent = [r for r in records if r.submitted and r.score is not None]
    out, tested = [], 0
    for outcome in OUTCOMES:
        k_all = sum(getattr(r, outcome) for r in sent)
        if not _usable(outcome, k_all, len(sent)):
            continue
        cands = []
        for t in SCORE_THRESHOLDS:
            hi = [r for r in sent if (r.score or 0) >= t]
            lo = [r for r in sent if (r.score or 0) < t]
            if len(hi) < MIN_SEGMENT or len(lo) < MIN_SEGMENT:
                continue
            a = Rate(sum(getattr(r, outcome) for r in hi), len(hi))
            b = Rate(sum(getattr(r, outcome) for r in lo), len(lo))
            p = fisher_exact(a.k, a.n - a.k, b.k, b.n - b.k)
            rest = f"jobs scoring below {t}"
            cands.append(_Candidate("score", str(t), f"{t}+", rest, outcome, a, b, p))
        tested += len(cands)
        best = None
        for cand, p_adj in zip(cands, holm([c.p for c in cands]), strict=True):
            insight = _comparison(f"Jobs scoring {cand.label}", cand, p_adj, len(cands))
            if (
                insight is not None
                and insight.direction == "better"
                and (best is None or cand.p < best[0])
            ):
                insight.kind, insight.key = "threshold", f"score:{cand.segment}:{outcome}"
                best = (cand.p, insight)
        if best:
            out.append(best[1])
    return out, tested


def _skills(records: list[Record]) -> tuple[list[Insight], int]:
    rows = [s for s in skill_correlations(records) if s["have"]["n"] >= 3 and s["lack"]["n"] >= 3]
    if not rows:
        return [], 0
    k_all = sum(r.interviewed for r in records if r.submitted)
    n_all = sum(r.submitted for r in records)
    if not _usable("interviewed", k_all, n_all):
        return [], 0
    adjusted = holm([float(s["p_value"]) for s in rows])
    out = []
    for s, p_adj in zip(rows, adjusted, strict=True):
        a = Rate(s["have"]["k"], s["have"]["n"])
        b = Rate(s["lack"]["k"], s["lack"]["n"])
        cand = _Candidate("skill", s["skill"], s["skill"], f"jobs where {s['skill']} was missing",
                          "interviewed", a, b, float(s["p_value"]))  # fmt: skip
        insight = _comparison(f"Jobs asking for {s['skill']} that you match", cand, p_adj,
                              len(rows))  # fmt: skip
        if insight is not None:
            insight.kind = "skill"
            out.append(insight)
    return out, len(rows)


def _facts(records: list[Record], ov: dict[str, Any]) -> list[Insight]:
    facts = []
    if ov["median_days_to_response"] is not None and ov["responded"] >= 3:
        facts.append(Insight(
            key="fact:response-time", kind="fact", confidence="fact",
            title=f"Employers replied after {ov['median_days_to_response']:.0f} days (median)",
            detail=f"Median over {ov['responded']} applications that got a reply.",
            evidence={"responded": ov["responded"]},
        ))  # fmt: skip
    silent, sent = ov["no_reply_after_14_days"], ov["submitted"]
    if silent >= 3:
        facts.append(Insight(
            key="fact:no-reply", kind="fact", confidence="fact",
            title=f"{silent} of {sent} applications have had no reply after 14 days",
            detail="Most replies come within two weeks; record any you received.",
            evidence={"silent": silent, "submitted": sent},
        ))  # fmt: skip
    acc = score_accuracy(records)["interviewed"]
    decided = acc["verdict"] not in ("not enough outcomes yet", "scores are too similar to judge",
                                     "no clear relationship yet")  # fmt: skip
    if acc["enough_data"] and decided:
        facts.append(Insight(
            key="score:accuracy", kind="score",
            confidence="fact", direction="better" if (acc["auc"] or 0) >= 0.6 else "neutral",
            title=f"Job scores: {acc['verdict']} (AUC {acc['auc']:.2f})",
            detail=(
                f"Interviewed applications scored {acc['mean_score_positive']} on average, the "
                f"others {acc['mean_score_negative']} ({acc['positives']} vs {acc['negatives']} "
                f"applications). AUC 0.5 is chance, 1.0 is perfect; p = {acc['p_value']:.3f}."
            ),
            evidence=acc,
        ))  # fmt: skip
    return facts
