"""Agent 5: rule-based job scoring (deterministic, no I/O, no tokens).

`score(job, profile, prefs)` rates how well a job fits the candidate on five
components, each 0-100 or None when there is nothing to judge it by:

* skills (35): known skills the posting asks for vs. the profile's skills;
  skills named in the requirements count double
* relevance (25): job title vs. the profile's target and related roles
  (fuzzy, with level words such as "Senior" removed)
* seniority (15): job level from the title vs. the candidate's level, and
  "N+ years of experience" vs. years of experience
* location (15): workplace type vs. the remote preference, job location vs.
  preferred locations
* salary (10): posted pay vs. the salary target

The overall score is the weighted mean of the components that could be
judged (weights renormalized), and `confidence` is the share of weight that
was available. Every number comes with its evidence in `breakdown`, and the
rationale is one plain sentence per component.

The optional Claude scorer (services/scoring_service.py) re-scores a
shortlist; this module never calls Claude.
"""

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from rapidfuzz import fuzz

from app.agents.agent_1_profile_inference import seniority_from
from app.agents.agent_4_rule_filtering import (
    ACCEPTED_WORKPLACES,
    fold,
    is_generic_remote,
    matches_location,
)
from app.parsing.skills import AMBIGUOUS, find_skills, normalize_skill
from app.utils.hashing import hash_json

SCORER_VERSION = "rules-1"

WEIGHTS: dict[str, float] = {
    "skills": 0.35,
    "relevance": 0.25,
    "seniority": 0.15,
    "location": 0.15,
    "salary": 0.10,
}
REQUIRED_SKILL_WEIGHT = 2.0
# Covering this share of the (weighted) skills already counts as a full match:
# postings list more than any one hire has.
FULL_SKILL_COVERAGE = 0.8

LEVEL_RANK: dict[str, int] = {
    "intern": 0, "entry": 1, "junior": 1, "mid": 2, "senior": 3, "lead": 4, "staff": 4,
    "manager": 4, "principal": 5, "director": 5, "executive": 6,
}  # fmt: skip
DEFAULT_JOB_LEVEL = "mid"  # a title without a level word ("Software Engineer")
FIRST_CHOICE_WORKPLACE = {"remote_only": "remote", "hybrid": "hybrid", "onsite": "onsite"}

_LEVEL_WORDS = re.compile(
    r"\b(?:senior|sr|junior|jr|staff|principal|lead|entry|level|mid|intern|internship|"
    r"associate|i{1,3}|iv|v|l\d|e\d|ic\d)\b"
)
_YEARS = re.compile(
    r"(\d{1,2})\s*\+?\s*(?:(?:-|–|to)\s*\d{1,2}\s*\+?\s*)?(?:years?|yrs?)(?:'|’)?\s+"
    r"(?:of\s+)?(?:[\w/&,-]+\s+){0,5}?(?:experience|exp)\b",
    re.IGNORECASE,
)
MAX_YEARS_REQUIRED = 20


@dataclass(frozen=True)
class ScoringJob:
    title: str
    company_name: str
    location: str | None = None
    remote_type: str = "unknown"
    salary_min: int | None = None
    salary_max: int | None = None
    salary_currency: str | None = None
    description: str = ""
    requirements: tuple[str, ...] = ()


@dataclass(frozen=True)
class ScoringProfile:
    skills: tuple[str, ...] = ()
    seniority: str | None = None
    years_experience: float | None = None
    roles: tuple[str, ...] = ()  # target roles, most suitable first
    related_roles: tuple[str, ...] = ()
    location: str | None = None


@dataclass(frozen=True)
class ScoringPreferences:
    preferred_locations: tuple[str, ...] = ()
    remote_preference: str = "any"
    salary_min: int | None = None
    salary_target: int | None = None
    salary_currency: str = "USD"


@dataclass
class Component:
    score: int | None
    summary: str
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass
class RuleScore:
    overall: int
    confidence: float
    components: dict[str, Component]
    matched_skills: list[str]
    missing_skills: list[str]
    rationale: str

    def component_score(self, name: str) -> int | None:
        return self.components[name].score

    def breakdown(self) -> dict[str, Any]:
        return {
            "version": SCORER_VERSION,
            "overall": self.overall,
            "confidence": self.confidence,
            "weights": WEIGHTS,
            "components": {name: asdict(c) for name, c in self.components.items()},
        }


# ------------------------------------------------------------------ skills
def _mentions(text: str, skill: str) -> bool:
    """A profile skill named in job text. Ambiguous short names ('Go', 'R')
    must appear with the same capitalization, others case-insensitively."""
    pattern = rf"(?<![\w+#.]){re.escape(skill)}(?![\w+#]|\.\w)"
    flags = 0 if (skill.lower() in AMBIGUOUS or len(skill) <= 2) else re.IGNORECASE
    return re.search(pattern, text, flags) is not None


def skills_component(
    job: ScoringJob, profile: ScoringProfile
) -> tuple[Component, list[str], list[str]]:
    req_text = "\n".join(job.requirements)
    all_text = "\n".join((job.title, req_text, job.description))
    required = find_skills(req_text)
    wanted = list(dict.fromkeys([*required, *find_skills(all_text)]))
    have = {normalize_skill(s).casefold(): normalize_skill(s) for s in profile.skills if s.strip()}
    # Candidate skills the taxonomy does not mine from prose ("Go", custom tools).
    for skill in have.values():
        if skill.casefold() not in {w.casefold() for w in wanted} and _mentions(all_text, skill):
            wanted.append(skill)
            if _mentions(req_text, skill):
                required.append(skill)
    if not wanted:
        return Component(None, "The posting names no skills we recognise"), [], []

    req = {s.casefold() for s in required}
    weight = {s: (REQUIRED_SKILL_WEIGHT if s.casefold() in req else 1.0) for s in wanted}
    matched = [s for s in wanted if s.casefold() in have]
    missing = [s for s in wanted if s.casefold() not in have]
    # Required skills first in both lists.
    matched.sort(key=lambda s: s.casefold() not in req)
    missing.sort(key=lambda s: s.casefold() not in req)
    coverage = sum(weight[s] for s in matched) / sum(weight.values())
    value = min(100, round(100 * coverage / FULL_SKILL_COVERAGE))
    summary = f"{len(matched)} of {len(wanted)} skills match"
    if missing:
        summary += f"; missing {', '.join(missing[:4])}"
    detail = {
        "matched": matched,
        "missing": missing,
        "required": [s for s in wanted if s.casefold() in req],
        "coverage": round(coverage, 3),
    }
    return Component(value, summary, detail), matched, missing


# --------------------------------------------------------------- relevance
def clean_title(title: str) -> str:
    """Title without level words, numbers and punctuation, for comparison."""
    t = re.sub(r"[^\w\s]", " ", fold(title))
    return " ".join(_LEVEL_WORDS.sub(" ", t).split())


def title_similarity(a: str, b: str) -> int:
    x, y = clean_title(a), clean_title(b)
    if not x or not y:
        return 0
    return round((fuzz.token_set_ratio(x, y) + fuzz.token_sort_ratio(x, y)) / 2)


def relevance_component(job: ScoringJob, profile: ScoringProfile) -> Component:
    candidates = [(r, 1.0) for r in profile.roles if r.strip()]
    candidates += [(r, 0.85) for r in profile.related_roles if r.strip()]
    if not candidates:
        return Component(None, "No target roles in the profile")
    best_role, best = "", -1.0
    for role, factor in candidates:
        value = title_similarity(job.title, role) * factor
        if value > best:
            best_role, best = role, value
    value = round(best)
    quality = "close to" if value >= 80 else "related to" if value >= 55 else "unlike"
    return Component(
        value, f"Title is {quality} '{best_role}'", {"best_role": best_role, "similarity": value}
    )


# --------------------------------------------------------------- seniority
def years_required(job: ScoringJob) -> int | None:
    """Smallest 'N+ years of experience' in the requirements, else the description."""
    for text in ("\n".join(job.requirements), job.description):
        found = [int(m) for m in _YEARS.findall(text) if 0 < int(m) <= MAX_YEARS_REQUIRED]
        if found:
            return min(found)
    return None


def _level_score(diff: int) -> int:
    if diff == 0:
        return 100
    if diff == 1:
        return 70  # a step up: a stretch
    if diff == -1:
        return 75  # a step down
    return 35 if abs(diff) == 2 else 10


def seniority_component(job: ScoringJob, profile: ScoringProfile) -> Component:
    job_level = seniority_from(job.title, None) or DEFAULT_JOB_LEVEL
    cand_level = profile.seniority or seniority_from(None, profile.years_experience)
    need = years_required(job)
    have = profile.years_experience
    parts: list[int] = []
    notes: list[str] = []
    if cand_level in LEVEL_RANK:
        diff = LEVEL_RANK[job_level] - LEVEL_RANK[cand_level]
        parts.append(_level_score(diff))
        notes.append(
            f"{job_level} role, you are {cand_level}"
            if diff
            else f"{_sentence(job_level)} role matches your level"
        )
    if need is not None and have is not None:
        parts.append(100 if have >= need else max(0, round(100 - 30 * (need - have))))
        notes.append(f"asks for {need}+ years, you have {have:g}")
    detail = {
        "job_level": job_level,
        "candidate_level": cand_level,
        "years_required": need,
        "years_experience": have,
    }
    if not parts:
        return Component(None, "Not enough information about the candidate's level", detail)
    return Component(round(sum(parts) / len(parts)), _sentence("; ".join(notes)), detail)


# ---------------------------------------------------------------- location
def location_component(
    job: ScoringJob, profile: ScoringProfile, prefs: ScoringPreferences
) -> Component:
    parts: list[int] = []
    notes: list[str] = []
    pref = prefs.remote_preference
    if pref != "any":
        if job.remote_type == "unknown":
            parts.append(60)
            notes.append("workplace type not stated")
        elif job.remote_type == FIRST_CHOICE_WORKPLACE.get(pref):
            parts.append(100)
            notes.append(f"{job.remote_type}, as you prefer")
        elif job.remote_type in ACCEPTED_WORKPLACES.get(pref, frozenset()):
            parts.append(80)
            notes.append(f"{job.remote_type} (acceptable)")
        else:
            parts.append(0)
            notes.append(f"{job.remote_type}, not what you want")

    wanted = [p for p in prefs.preferred_locations if p.strip() and fold(p) != "remote"]
    if not wanted and profile.location:
        wanted = [profile.location]
    is_remote = job.remote_type == "remote" and pref != "onsite"
    if wanted or is_remote:
        if is_remote and is_generic_remote(job.location):
            parts.append(100)
            notes.append("remote with no location limit")
        elif not job.location:
            parts.append(60)
            notes.append("location not listed")
        else:
            hit = next((i for i, p in enumerate(wanted) if matches_location(job.location, p)), None)
            if hit is not None:
                parts.append(max(85, 100 - 5 * hit))
                notes.append(f"in {wanted[hit]}")
            else:
                parts.append(70 if is_remote else 20)
                notes.append(f"{job.location} is not a preferred location")
    if not parts:
        return Component(None, "No location or workplace preference to compare")
    return Component(
        round(sum(parts) / len(parts)),
        _sentence("; ".join(notes)),
        {"remote_type": job.remote_type, "location": job.location, "preferred": wanted},
    )


# ------------------------------------------------------------------ salary
def salary_component(job: ScoringJob, prefs: ScoringPreferences) -> Component:
    target = prefs.salary_target or prefs.salary_min
    top = job.salary_max if job.salary_max is not None else job.salary_min
    if target is None:
        return Component(None, "No salary target set")
    if top is None:
        return Component(None, "Salary not listed")
    currency = job.salary_currency or prefs.salary_currency
    if currency != prefs.salary_currency:
        return Component(None, f"Salary in {currency}, not compared")
    detail = {"job_max": top, "target": target, "currency": currency}
    if top >= target:
        return Component(100, f"Pays up to {currency} {top:,}, meets your target", detail)
    value = max(0, round(100 - (1 - top / target) * 250))
    summary = f"Pays up to {currency} {top:,}, below your target of {target:,}"
    return Component(value, summary, detail)


# ------------------------------------------------------------------- score
def score(job: ScoringJob, profile: ScoringProfile, prefs: ScoringPreferences) -> RuleScore:
    skills, matched, missing = skills_component(job, profile)
    components = {
        "skills": skills,
        "relevance": relevance_component(job, profile),
        "seniority": seniority_component(job, profile),
        "location": location_component(job, profile, prefs),
        "salary": salary_component(job, prefs),
    }
    known = {n: c.score for n, c in components.items() if c.score is not None}
    weight = sum(WEIGHTS[n] for n in known)
    overall = round(sum(WEIGHTS[n] * v for n, v in known.items()) / weight) if weight else 0
    rationale = (
        " ".join(
            f"{_sentence(name)}: {c.summary}."
            for name, c in components.items()
            if c.score is not None
        )
        or "Not enough information to score this job."
    )
    return RuleScore(
        overall=overall,
        confidence=round(weight, 2),
        components=components,
        matched_skills=matched,
        missing_skills=missing,
        rationale=rationale,
    )


def _sentence(text: str) -> str:
    return text[:1].upper() + text[1:]


def fingerprint(job: ScoringJob, profile: ScoringProfile, prefs: ScoringPreferences) -> str:
    """Hash of the scorer version and every input it reads."""
    return hash_json(
        {
            "version": SCORER_VERSION,
            "job": asdict(job),
            "profile": asdict(profile),
            "prefs": asdict(prefs),
        }
    )
