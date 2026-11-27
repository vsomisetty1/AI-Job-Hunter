"""Agent 6: resume tailoring.

Builds a version of the candidate's parsed resume aimed at one job, without
claiming anything the resume does not say.

Deterministic (always, no tokens):
1. Skills: the ones the job asks for move to the front, in the job's order,
   and take the canonical spelling the posting uses ("postgres" ->
   "PostgreSQL"). Skill groups are reordered the same way.
2. Bullets: within each role, bullets that mention the job's skills move up
   (roles stay in chronological order).
3. Projects: the most relevant first.
4. Summary: opens with one sentence built only from profile facts: level,
   target role, years of experience and the matching skills.

Optional (Claude): rewords the summary and some bullets. Every rewording is
checked by `app.agents.truthfulness`; one that adds a skill or a number is
dropped and noted, and if the finished resume fails the structural check the
whole Claude pass is discarded.

Every change is recorded with section, item, field, before, after, reason and
time. Matched and missing skills come from the same logic as Agent 5's score.
"""

import json
import logging
import math
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.agents.agent_5_job_scoring import (
    ScoringJob,
    ScoringProfile,
    skills_component,
    title_similarity,
)
from app.agents.base import Agent
from app.agents.truthfulness import (
    Facts,
    check_tailored,
    check_text,
    facts_from,
    numbers_in,
    skills_in,
)
from app.llm.client import LLMError
from app.llm.prompts.resume_tailor import RESUME_TAILOR
from app.parsing.skills import normalize_skill
from app.schemas.package import TailoringRewriteOutput
from app.schemas.parsed_resume import ParsedResume

logger = logging.getLogger(__name__)

TAILORING_VERSION = "tailor-1"
MAX_HEADLINE_SKILLS = 4
LEVEL_WORDS = {
    "junior": "Junior",
    "mid": "Mid-level",
    "senior": "Senior",
    "staff": "Staff",
    "principal": "Principal",
    "lead": "Lead",
}


@dataclass(frozen=True)
class TailoringJob:
    title: str
    company_name: str
    description: str = ""
    requirements: tuple[str, ...] = ()


@dataclass(frozen=True)
class CandidateFacts:
    """Profile facts (the profile may know skills the resume lists elsewhere)."""

    skills: tuple[str, ...] = ()
    seniority: str | None = None
    years_experience: float | None = None
    roles: tuple[str, ...] = ()


@dataclass
class TailoringResult:
    content: ParsedResume
    changes: list[dict[str, Any]]
    matched_skills: list[str]
    missing_skills: list[str]
    notes: list[str]
    method: str = "rules"
    model: str | None = None
    rejected_rewrites: list[dict[str, Any]] = field(default_factory=list)

    @property
    def summary(self) -> str:
        n = len(self.changes)
        if n == 0:
            return "No changes needed: the resume already leads with what this job asks for."
        by = "with Claude rewording" if self.method == "claude" else "by reordering"
        return f"Tailored {by}: {n} change{'s' if n != 1 else ''}."

    def tailoring_json(self) -> dict[str, Any]:
        return {
            "version": TAILORING_VERSION,
            "method": self.method,
            "model": self.model,
            "matched_skills": self.matched_skills,
            "missing_skills": self.missing_skills,
            "notes": self.notes,
            "rejected_rewrites": self.rejected_rewrites,
        }


# ------------------------------------------------------------------ helpers
def _change(
    section: str,
    field_name: str,
    before: Any,
    after: Any,
    reason: str,
    now: datetime,
    item: str | None = None,
) -> dict[str, Any]:
    return {
        "section": section,
        "item": item,
        "field": field_name,
        "before": before,
        "after": after,
        "reason": reason,
        "at": now.isoformat(),
    }


def _role_label(title: str | None, company: str | None) -> str:
    return " at ".join(x for x in (title, company) if x) or "Role"


def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def job_skills(
    job: TailoringJob, candidate: CandidateFacts, resume: ParsedResume
) -> tuple[list[str], list[str]]:
    """(matched, missing) skills, as Agent 5 computes them, with the resume's
    skills counted as the candidate's."""
    skills = tuple(dict.fromkeys([*candidate.skills, *resume.skills]))
    comp, matched, missing = skills_component(
        ScoringJob(
            job.title, job.company_name, description=job.description, requirements=job.requirements
        ),
        ScoringProfile(skills=skills),
    )
    del comp
    return matched, missing


def _relevance(text: str, wanted: set[str], facts: Facts) -> int:
    return len(skills_in(text, facts) & wanted)


def _rank(items: list[str], key: Any) -> list[str]:
    """Stable sort, most relevant first."""
    return [x for _, x in sorted(enumerate(items), key=lambda p: (-key(p[1]), p[0]))]


# ------------------------------------------------------------ deterministic
def tailor(
    resume: ParsedResume,
    job: TailoringJob,
    candidate: CandidateFacts,
    *,
    now: datetime | None = None,
) -> TailoringResult:
    now = now or datetime.now(UTC)
    out = resume.model_copy(deep=True)
    facts = facts_from(resume, extra_skills=candidate.skills)
    matched, missing = job_skills(job, candidate, resume)
    wanted = {s.casefold() for s in matched}
    order = {s.casefold(): i for i, s in enumerate(matched)}
    changes: list[dict[str, Any]] = []
    notes: list[str] = []

    # 1. Skills: job's skills first, in the job's spelling.
    if out.skills:
        renamed: list[str] = []
        for s in out.skills:
            canonical = normalize_skill(s)
            if canonical != s and canonical.casefold() in wanted:
                changes.append(
                    _change(
                        "skills",
                        "name",
                        s,
                        canonical,
                        "Uses the posting's spelling of this skill",
                        now,
                    )
                )
                s = canonical
            renamed.append(s)
        renamed = list(dict.fromkeys(renamed))
        ranked = sorted(
            renamed,
            key=lambda s: (order.get(normalize_skill(s).casefold(), len(order)), renamed.index(s)),
        )
        if ranked != renamed:
            moved = [s for s in ranked if normalize_skill(s).casefold() in wanted]
            changes.append(
                _change(
                    "skills",
                    "order",
                    renamed,
                    ranked,
                    f"Moved the skills this job asks for to the front: {_join(moved)}",
                    now,
                )
            )
        out.skills = ranked
    for group in out.skill_groups:
        ranked = sorted(
            group.skills,
            key=lambda s: (
                order.get(normalize_skill(s).casefold(), len(order)),
                group.skills.index(s),
            ),
        )
        if ranked != group.skills:
            changes.append(
                _change(
                    "skills",
                    "order",
                    group.skills,
                    ranked,
                    "Job-relevant skills first",
                    now,
                    item=group.name,
                )
            )
            group.skills = ranked
    if len(out.skill_groups) > 1:
        before_groups = [g.name for g in out.skill_groups]
        out.skill_groups = sorted(
            out.skill_groups,
            key=lambda g: (
                -sum(normalize_skill(s).casefold() in wanted for s in g.skills),
                before_groups.index(g.name),
            ),
        )
        after_groups = [g.name for g in out.skill_groups]
        if after_groups != before_groups:
            changes.append(
                _change(
                    "skills",
                    "group_order",
                    before_groups,
                    after_groups,
                    "Groups with more of the job's skills first",
                    now,
                )
            )

    # 2. Bullets within each role.
    for role in out.experience:
        ranked = _rank(role.bullets, lambda b: _relevance(b, wanted, facts))
        if ranked != role.bullets:
            top = sorted(skills_in(ranked[0], facts) & wanted)
            names = [m for m in matched if m.casefold() in top] or top
            changes.append(
                _change(
                    "experience",
                    "bullets",
                    role.bullets,
                    ranked,
                    f"Leads with the work that uses {_join(names)}"
                    if names
                    else "Leads with the most relevant work",
                    now,
                    item=_role_label(role.title, role.company),
                )
            )
            role.bullets = ranked

    # 3. Projects.
    if len(out.projects) > 1:
        names_before = [p.name for p in out.projects]
        out.projects = sorted(
            out.projects,
            key=lambda p: (
                -_relevance(
                    " ".join([p.name, p.description or "", *p.technologies, *p.bullets]),
                    wanted,
                    facts,
                ),
                names_before.index(p.name),
            ),
        )
        names_after = [p.name for p in out.projects]
        if names_after != names_before:
            changes.append(
                _change(
                    "projects",
                    "order",
                    names_before,
                    names_after,
                    "Most relevant projects first",
                    now,
                )
            )

    # 4. Summary headline from profile facts.
    # If the candidate's own summary already states their years, do not add a
    # second, possibly different figure computed from role dates.
    states_years = bool(re.search(r"\b\d+\+?\s*(?:years|yrs)\b", out.summary or "", re.I))
    headline = headline_for(
        job, candidate, [m for m in matched if facts.has_skill(m)], with_years=not states_years
    )
    if headline and check_text(headline, facts, allow_numbers=_computed_numbers(candidate)):
        headline = None  # e.g. a profile role naming a skill the resume never mentions
    if headline and not (out.summary or "").startswith(headline):
        new_summary = f"{headline} {out.summary}".strip() if out.summary else headline
        changes.append(
            _change(
                "summary",
                "text",
                out.summary,
                new_summary,
                "Opens with the role, experience and skills this job asks for",
                now,
            )
        )
        out.summary = new_summary

    if missing:
        notes.append(
            f"The posting asks for {_join(missing)}, which your resume does not mention. "
            "Nothing was added; if you have this experience, add it to your resume first."
        )
    if not matched:
        notes.append("No skills from the posting were found in your resume.")
    result = TailoringResult(out, changes, matched, missing, notes)
    problems = check_tailored(
        resume, out, extra_skills=candidate.skills, allow_numbers=_computed_numbers(candidate)
    )
    if problems:  # a bug, not a judgement call: never ship it
        raise AssertionError(f"deterministic tailoring broke truthfulness: {problems}")
    return result


def _years(candidate: CandidateFacts) -> int | None:
    y = candidate.years_experience
    return int(math.floor(y)) if y is not None and y >= 1 else None


def _computed_numbers(candidate: CandidateFacts) -> list[str]:
    y = _years(candidate)
    return [str(y)] if y is not None else []


def headline_for(
    job: TailoringJob, candidate: CandidateFacts, skills: list[str], *, with_years: bool = True
) -> str | None:
    """'Senior Backend Engineer with 7+ years of experience in Python and AWS.'"""
    if not candidate.roles:
        return None
    role = max(candidate.roles, key=lambda r: title_similarity(job.title, r))
    level = LEVEL_WORDS.get(candidate.seniority or "")
    if level and level.split("-")[0].lower() not in role.lower():
        role = f"{level} {role}"
    years = _years(candidate) if with_years else None
    text = role
    if years is not None:
        text += f" with {years}+ years of experience"
    if skills:
        text += (" in " if years is not None else " experienced in ") + _join(
            skills[:MAX_HEADLINE_SKILLS]
        )
    return text + "."


# ------------------------------------------------------------------ Claude
def apply_rewrites(
    base: TailoringResult,
    original: ParsedResume,
    rewrites: TailoringRewriteOutput,
    candidate: CandidateFacts,
    *,
    model: str | None,
    now: datetime | None = None,
) -> TailoringResult:
    """Apply Claude's rewordings that pass the truthfulness checks."""
    now = now or datetime.now(UTC)
    out = base.content.model_copy(deep=True)
    facts = facts_from(original, extra_skills=candidate.skills)
    changes = list(base.changes)
    rejected: list[dict[str, Any]] = []
    notes = list(base.notes)
    seen: set[tuple[int, int]] = set()
    for rw in rewrites.bullets[:12]:
        if not (0 <= rw.role < len(out.experience)) or (rw.role, rw.index) in seen:
            continue
        role = out.experience[rw.role]
        if not (0 <= rw.index < len(role.bullets)):
            continue
        seen.add((rw.role, rw.index))
        old, new = role.bullets[rw.index], rw.text.strip()
        if not new or new == old:
            continue
        role_numbers = numbers_in("\n".join(original.experience[rw.role].bullets))
        bullet_facts = Facts(facts.skills, frozenset(role_numbers), facts.listed_skills)
        problems = check_text(new, bullet_facts)
        if len(new) > len(old) * 1.5 + 40:
            problems.append("much longer than the original")
        if problems:
            rejected.append(
                {"item": _role_label(role.title, role.company), "text": new, "problems": problems}
            )
            continue
        role.bullets[rw.index] = new
        changes.append(
            _change(
                "experience",
                "bullet",
                old,
                new,
                rw.reason or "Reworded to emphasise relevant work",
                now,
                item=_role_label(role.title, role.company),
            )
        )
    if rewrites.summary and rewrites.summary.strip() != (out.summary or ""):
        new_summary = rewrites.summary.strip()
        problems = check_text(new_summary, facts, allow_numbers=_computed_numbers(candidate))
        if problems:
            rejected.append({"item": "summary", "text": new_summary, "problems": problems})
        else:
            changes.append(
                _change(
                    "summary",
                    "text",
                    out.summary,
                    new_summary,
                    rewrites.summary_reason or "Reworded for this job",
                    now,
                )
            )
            out.summary = new_summary
    if rejected:
        notes.append(
            f"{len(rejected)} suggested rewording(s) were dropped because they added skills or "
            "numbers your resume does not have."
        )
    final = check_tailored(
        original, out, extra_skills=candidate.skills, allow_numbers=_computed_numbers(candidate)
    )
    if final:
        logger.warning("discarding Claude tailoring: %s", final)
        base.notes.append("Claude's rewording was discarded: it failed the truthfulness check.")
        base.rejected_rewrites = rejected
        return base
    return TailoringResult(
        out,
        changes,
        base.matched_skills,
        base.missing_skills,
        notes,
        method="claude",
        model=model,
        rejected_rewrites=rejected,
    )


def rewrite_inputs(result: TailoringResult, job: TailoringJob) -> dict[str, str]:
    resume = result.content
    roles = [
        {
            "role": i,
            "title": e.title,
            "company": e.company,
            "bullets": [{"index": j, "text": b} for j, b in enumerate(e.bullets)],
        }
        for i, e in enumerate(resume.experience)
    ]
    return {
        "job_json": json.dumps(
            {
                "title": job.title,
                "company": job.company_name,
                "skills_to_emphasise": result.matched_skills,
                "requirements": list(job.requirements)[:15],
            },
            ensure_ascii=False,
        ),
        "resume_json": json.dumps(
            {"summary": resume.summary, "experience": roles}, ensure_ascii=False
        ),
    }


class ResumeTailoringAgent(Agent):
    name = "agent_6_resume_tailoring"

    async def run(
        self,
        resume: ParsedResume,
        job: TailoringJob,
        candidate: CandidateFacts,
        *,
        use_llm: bool,
    ) -> TailoringResult:
        result = tailor(resume, job, candidate)
        if not (use_llm and self.llm.enabled):
            if use_llm:
                result.notes.append("Claude rewording skipped: no ANTHROPIC_API_KEY configured.")
            return result
        async with self.track(input_summary={"job": job.title, "company": job.company_name}) as run:
            inputs = rewrite_inputs(result, job)
            try:
                answer = await self.llm.structured(
                    RESUME_TAILOR,
                    model=self.llm.settings.claude_model_writing,
                    job_json=inputs["job_json"],
                    resume_json=inputs["resume_json"],
                )
            except LLMError as exc:
                result.notes.append(f"Claude rewording skipped: {exc.message}")
                run.output_summary["error"] = exc.message
                return result
            self.record(run, RESUME_TAILOR.name, answer)
            tailored = apply_rewrites(
                result, resume, answer.output, candidate, model=answer.usage.model
            )
            run.output_summary.update(
                method=tailored.method,
                changes=len(tailored.changes),
                rejected=len(tailored.rejected_rewrites),
            )
            return tailored
