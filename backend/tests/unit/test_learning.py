"""Learning engine, pure parts: statistics, job families, metrics, outcome
derivation, insights (only when the data supports them) and recommendations.

Records here are synthetic with KNOWN effects, so the tests check that the
engine finds a real difference, ignores noise, and says nothing from too
little data."""

import itertools
import math
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.learning import insights as engine
from app.learning.dataset import Record
from app.learning.families import job_family
from app.learning.metrics import (
    funnel,
    overview,
    score_accuracy,
    score_band,
    segments,
    skill_correlations,
)
from app.learning.recommendations import Context, recommend
from app.learning.stats import Rate, auc, fisher_exact, holm, median, wilson
from app.models.learning import InterviewEvent
from app.services.outcome_service import derive

NOW = datetime(2026, 11, 27, 12, tzinfo=UTC)
_ids = itertools.count()


def rec(
    *,
    submitted: bool = True,
    responded: bool = False,
    interviewed: bool = False,
    offered: bool = False,
    rejected: bool = False,
    days_ago: int = 30,
    **kw,
) -> Record:
    n = next(_ids)
    sent = NOW - timedelta(days=days_ago)
    base = dict(
        job_id=f"j{n}", job_title="Backend Engineer", family="backend", remote_type="hybrid",
        company_id=f"c{n % 7}", company=f"Company {n % 7}", industry=None, platform="greenhouse",
        package_id=f"p{n}", package_status="submitted" if submitted else "approved",
        package_versions=1, score=75, score_method="rules", cover_letter=True,
        tailoring_method="rules", resume_variant="resume.pdf v2",
        generated_at=sent - timedelta(days=1), approved_at=sent - timedelta(hours=1),
    )  # fmt: skip
    base.update(kw)
    r = Record(**base)
    if submitted:
        r.submitted_at = sent
        r.application_id = f"a{n}"
        r.applied_via = "manual"
        if responded or interviewed or offered or rejected:
            r.responded_at = sent + timedelta(days=5)
        if interviewed or offered:
            r.first_interview_at = sent + timedelta(days=8)
        if offered:
            r.offer_at = sent + timedelta(days=30)
        if rejected:
            r.rejected_at = sent + timedelta(days=20)
    return r


def many(n: int, **kw) -> list[Record]:
    return [rec(**kw) for _ in range(n)]


# ------------------------------------------------------------------ stats
def test_wilson_interval_is_sane_at_the_edges():
    lo, hi = wilson(0, 5)
    assert lo == 0 and 0.4 < hi < 0.5
    lo, hi = wilson(5, 5)
    assert 0.5 < lo < 0.6 and hi == 1
    assert wilson(0, 0) is None
    assert Rate(3, 10).as_dict()["rate"] == 0.3


def test_fisher_exact_matches_known_values():
    # Lady tasting tea: 3 of 4 vs 1 of 4 -> two-sided p = 0.4857
    assert math.isclose(fisher_exact(3, 1, 1, 3), 0.4857, abs_tol=1e-3)
    assert math.isclose(fisher_exact(10, 0, 0, 10), 1.0825e-05, rel_tol=1e-3)
    assert fisher_exact(0, 0, 3, 4) == 1.0


def test_auc_p_value():
    from app.learning.stats import auc_p_value

    assert auc_p_value([10, 11, 12, 13, 14, 15], [1, 2, 3, 4, 5, 6]) < 0.01
    assert auc_p_value([1, 3, 5], [2, 4, 6]) > 0.5
    assert auc_p_value([], [1]) is None and auc_p_value([1, 1], [1, 1]) == 1.0


def test_holm_auc_and_median():
    assert holm([0.01, 0.04, 0.03]) == [0.03, 0.06, 0.06]
    assert auc([3, 4], [1, 2]) == 1.0 and auc([1, 2], [1, 2]) == 0.5 and auc([], [1]) is None
    assert median([3, 1, 2]) == 2 and median([1, 2, 3, 4]) == 2.5 and median([]) is None


# --------------------------------------------------------------- families
@pytest.mark.parametrize(
    ("title", "family"),
    [
        ("Senior Backend Engineer", "backend"),
        ("Software Engineer, Payments API", "backend"),
        ("Staff Machine Learning Engineer", "ml_ai"),
        ("Frontend Engineer", "frontend"),
        ("Full-Stack Developer", "fullstack"),
        ("Site Reliability Engineer", "infrastructure"),
        ("iOS Engineer", "mobile"),
        ("Engineering Manager, Platform", "management"),
        ("Data Engineer", "data"),
        ("Software Engineer", "engineering"),
        ("Account Executive", "other"),
    ],
)
def test_job_families(title, family):
    assert job_family(title) == family


# -------------------------------------------------------- outcome derivation
def ev(stage, status="completed", days=0):
    return InterviewEvent(application_id=uuid.uuid4(), stage=stage, status=status,
                          occurred_at=NOW + timedelta(days=days))  # fmt: skip


def test_milestones_and_status_are_derived_from_events():
    m = derive([])
    assert (m.status, m.responded_at, m.current_stage) == ("submitted", None, None)
    m = derive([ev("recruiter_response", days=1)])
    assert m.status == "submitted" and m.responded_at == NOW + timedelta(days=1)
    m = derive([ev("recruiter_response", days=1), ev("phone_screen", "scheduled", days=3)])
    assert m.status == "interview" and m.first_interview_at == NOW + timedelta(days=3)
    assert m.current_stage == "phone_screen"
    # A cancelled screen did not happen.
    m = derive([ev("phone_screen", "cancelled", days=3)])
    assert m.status == "submitted" and m.responded_at is None and m.first_interview_at is None
    # The latest ending decides; an offer then a withdrawal ends withdrawn.
    m = derive([ev("onsite", days=5), ev("offer", days=9), ev("withdrawal", days=10)])
    assert (m.status, m.offer_at, m.withdrawn_at) == (
        "withdrawn", NOW + timedelta(days=9), NOW + timedelta(days=10))  # fmt: skip
    # A rejection without interviews is still a response.
    m = derive([ev("rejection", days=4)])
    assert m.status == "rejected" and m.responded_at == m.rejected_at
    # Withdrawing is not an employer response.
    assert derive([ev("withdrawal", days=2)]).responded_at is None


# ---------------------------------------------------------------- metrics
def test_funnel_and_overview_count_each_step():
    records = (
        many(4, submitted=False, approved_at=None)  # generated only
        + many(2, submitted=False)  # approved, not sent
        + many(6)  # sent, silent
        + many(2, rejected=True)
        + many(3, interviewed=True)
        + many(1, offered=True)
        + many(2, days_ago=3)  # sent recently: still awaiting a reply
    )
    steps = {s["stage"]: s["count"] for s in funnel(records)}
    assert steps == {"generated": 20, "approved": 16, "submitted": 14, "responded": 6,
                     "interviewed": 4, "offered": 1}  # fmt: skip
    ov = overview(records, NOW)
    assert ov["interview_rate"]["k"] == 4 and ov["interview_rate"]["n"] == 14
    assert ov["awaiting_reply"] == 2 and ov["no_reply_after_14_days"] == 6
    assert ov["median_days_to_response"] == 5.0 and ov["enough_data"] is True


def test_score_accuracy_bands_and_auc():
    records = many(8, score=90, interviewed=True) + many(2, score=88) + many(10, score=60)
    acc = score_accuracy(records)
    assert [b["key"] for b in acc["bands"]] == ["60-69", "85+"]
    assert acc["interviewed"]["auc"] == 1.0 and acc["interviewed"]["enough_data"]
    assert acc["interviewed"]["verdict"] == "scores predict outcomes well"
    assert score_band(84) == "80-84" and score_band(None) is None
    # Scores packed together, or no real relation: no verdict either way.
    close = many(6, score=92, interviewed=True) + many(6, score=90)
    assert score_accuracy(close)["interviewed"]["verdict"] == "scores are too similar to judge"
    mixed = (many(3, score=90, interviewed=True) + many(3, score=60, interviewed=True)
             + many(3, score=88) + many(3, score=62))  # fmt: skip
    assert score_accuracy(mixed)["interviewed"]["verdict"] == "no clear relationship yet"
    assert "score:accuracy" not in {i["key"] for i in engine.generate(mixed, NOW)["insights"]}
    # Too few outcomes: no verdict.
    assert score_accuracy(many(3, interviewed=True))["interviewed"]["verdict"] == (
        "not enough outcomes yet"
    )


def test_skill_correlations_compare_having_vs_lacking():
    records = many(6, matched_skills=["Go"], interviewed=True) + many(
        6, missing_skills=["Go"]) + many(2, matched_skills=["Rust"])  # fmt: skip
    go = next(s for s in skill_correlations(records) if s["skill"] == "Go")
    assert go["have"]["k"] == 6 and go["have"]["n"] == 6 and go["lack"]["k"] == 0
    assert go["p_value"] < 0.01
    assert all(s["skill"] != "Rust" for s in skill_correlations(records))  # below min support


def test_segments_leave_out_unknown_keys():
    records = many(3, industry="Fintech") + many(2)
    segs = segments(records, lambda r: r.industry)
    assert [(s.key, s.submitted) for s in segs] == [("Fintech", 3)]


# ---------------------------------------------------------------- insights
def test_no_comparisons_from_too_little_data():
    report = engine.generate(many(4, interviewed=True) + many(4), NOW)
    assert report["status"] == "insufficient_data" and report["comparisons_tested"] == 0
    assert all(i["kind"] == "fact" for i in report["insights"])
    assert "Comparisons start at 10" in report["message"]


def test_a_real_score_effect_is_found_with_its_numbers():
    # 85+: 9 of 12 interviewed; below 85: 2 of 12.
    records = (
        many(9, score=90, interviewed=True) + many(3, score=88)
        + many(2, score=70, interviewed=True) + many(10, score=65)
    )  # fmt: skip
    report = engine.generate(records, NOW)
    assert report["status"] == "ok" and report["comparisons_tested"] > 0
    threshold = [i for i in report["insights"] if i["kind"] == "threshold"
                 and i["outcome"] == "interviewed"]  # fmt: skip
    assert len(threshold) == 1
    i = threshold[0]
    assert i["title"].startswith("Jobs scoring ") and "as often as jobs scoring below" in i["title"]
    assert i["direction"] == "better" and i["confidence"] in ("high", "medium")
    assert i["evidence"]["p_adjusted"] <= engine.MAX_P
    assert "Fisher exact p" in i["detail"]


def test_noise_produces_no_comparison_insight():
    # Same 30 % interview rate in every group: nothing to say.
    records = []
    for platform in ("greenhouse", "lever", "ashby"):
        records += many(3, platform=platform, interviewed=True) + many(7, platform=platform)
    report = engine.generate(records, NOW)
    assert report["status"] == "ok"
    assert report["comparisons_tested"] >= 3  # the groups were compared, and found equal
    assert not [i for i in report["insights"] if i["kind"] in ("comparison", "threshold")]


def test_cover_letter_and_remote_comparisons_use_real_counts():
    records = (
        many(8, cover_letter=True, responded=True) + many(2, cover_letter=True)
        + many(1, cover_letter=False, responded=True) + many(9, cover_letter=False)
    )  # fmt: skip
    report = engine.generate(records, NOW)
    letter = [i for i in report["insights"] if i["dimension"] == "cover_letter"
              and i["outcome"] == "responded"]  # fmt: skip
    assert len(letter) == 1  # A vs B is one comparison, not two mirrored ones
    assert "8 of 10 (80%) vs 1 of 10 (10%)" in letter[0]["detail"]


def test_an_outcome_that_never_varies_is_not_analysed():
    report = engine.generate(many(12, platform="lever") + many(12, platform="ashby"), NOW)
    assert not [i for i in report["insights"] if i["kind"] == "comparison"]


# --------------------------------------------------------- recommendations
def test_recommendations_follow_insights_and_counts():
    records = (
        many(9, score=90, interviewed=True) + many(3, score=88)
        + many(2, score=70, interviewed=True) + many(10, score=65, missing_skills=["Kubernetes"])
        + many(3, submitted=False, score=60)
    )  # fmt: skip
    report = engine.generate(records, NOW)
    recs = {r.key: r for r in recommend(records, report["insights"], Context(now=NOW))}
    score = next(r for k, r in recs.items() if k.startswith("min-score:"))
    assert score.category == "targeting" and score.action_href.startswith("/jobs?min_score=")
    assert "package(s) not yet sent score below" in score.rationale
    gap = recs["skill-gap:kubernetes"]
    assert "Add it only if it is true" in gap.rationale
    # A skill already on the profile is not suggested.
    again = recommend(records, report["insights"],
                      Context(profile_skills=frozenset({"kubernetes"}), now=NOW))  # fmt: skip
    assert "skill-gap:kubernetes" not in {r.key for r in again}


def test_data_hygiene_recommendations():
    records = many(3, days_ago=40) + many(2, days_ago=40, responded=True)
    recs = {r.key: r for r in recommend(records, [], Context(stale_scheduled=2, now=NOW))}
    assert recs["data:record-outcomes"].title == "Record outcomes for 3 application(s)"
    assert recs["data:update-scheduled"].priority == "high"
    assert recs["data:more-history"].evidence == {"submitted": 5, "needed": 10}
    # With enough history and no industries set, ask for industries (never guessed).
    more = many(12, days_ago=5)
    keys = {r.key for r in recommend(more, [], Context(now=NOW))}
    assert "data:set-industries" in keys and "data:more-history" not in keys


def test_nothing_is_recommended_from_nothing():
    assert [r.key for r in recommend([], [], Context(now=NOW))] == ["data:more-history"]
