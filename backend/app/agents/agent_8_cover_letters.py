"""Agent 8: cover letter generation.

Rule-based (always, no tokens): the letter is assembled from facts only:
the role and company from the posting; level, years, latest role and the
matching skills from the profile; and the most relevant resume bullets,
quoted as written ("As Senior Engineer at Acme: Built billing APIs in
Python."). Sentences are added or dropped to land between 150 and 300 words;
a sparse resume can make it shorter, and that is noted rather than padded
with invented material.

Claude (optional) writes the letter from the same facts. It is used only if it
passes `app.agents.truthfulness.check_text` (no skill or number the resume
lacks), is 150-300 words and names the company; otherwise the rule-based
letter is kept with a note.
"""

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from app.agents.agent_6_resume_tailoring import (
    LEVEL_WORDS,
    CandidateFacts,
    TailoringJob,
    _join,
)
from app.agents.agent_7_resume_generation import LetterDoc
from app.agents.base import Agent
from app.agents.truthfulness import Facts, check_text, facts_from, skills_in
from app.llm.client import LLMError
from app.llm.prompts.cover_letter import COVER_LETTER
from app.schemas.parsed_resume import ParsedResume

logger = logging.getLogger(__name__)

MIN_WORDS, MAX_WORDS = 150, 300
MAX_EVIDENCE = 8


def word_count(text: str) -> int:
    return len(re.findall(r"\b[\w'’-]+\b", text))


def _sentence(text: str) -> str:
    text = text.strip().rstrip(";,")
    return text if text.endswith((".", "!", "?")) else text + "."


@dataclass(frozen=True)
class CoverLetterInput:
    resume: ParsedResume  # the tailored version: most relevant bullets first
    job: TailoringJob
    candidate: CandidateFacts
    matched_skills: tuple[str, ...]
    sender_name: str
    sender_contact: str = ""


@dataclass
class CoverLetterResult:
    paragraphs: list[str]
    greeting: str
    recipient: str
    method: str = "rules"
    model: str | None = None
    notes: list[str] = field(default_factory=list)
    facts_used: list[str] = field(default_factory=list)

    @property
    def body(self) -> str:
        return "\n\n".join(self.paragraphs)

    @property
    def word_count(self) -> int:
        return word_count(self.body)

    @property
    def text(self) -> str:
        """The full letter as stored (greeting, body, sign-off)."""
        return f"{self.greeting}\n\n{self.body}"

    def letter(self, inp: CoverLetterInput, today: date | None = None) -> LetterDoc:
        return LetterDoc(
            sender_name=inp.sender_name,
            sender_contact=inp.sender_contact,
            date=today or datetime.now(UTC).date(),
            recipient=self.recipient,
            greeting=self.greeting,
            paragraphs=self.paragraphs,
        )


# Bullets usually start with a past-tense verb ("Built ..."); those read well
# after "I". Anything else is quoted after a colon instead.
_IRREGULAR_VERBS = {
    "built", "led", "ran", "wrote", "cut", "grew", "made", "drove", "won", "set", "kept",
    "brought", "sold", "taught", "chose", "gave", "found", "began", "took", "held", "spoke",
    "rebuilt", "rewrote", "oversaw", "undertook", "shipped", "owned",
}  # fmt: skip


def _starts_with_verb(bullet: str) -> bool:
    first = bullet.split(maxsplit=1)[0] if bullet.split() else ""
    word = first.lower().strip(",.;:")
    return (
        first[:1].isupper()
        and first[1:].islower()
        and (word.endswith("ed") or word in _IRREGULAR_VERBS)
    )


@dataclass(frozen=True)
class Evidence:
    group: int  # position of the role or project in the resume
    label: str  # "Senior Engineer at Acme" or a project name
    text: str
    project: bool = False


def evidence_items(resume: ParsedResume, wanted: set[str], facts: Facts) -> list[Evidence]:
    """Resume bullets and projects, most relevant first (stable)."""
    scored: list[tuple[int, int, Evidence]] = []
    order = 0
    for g, role in enumerate(resume.experience):
        label = " at ".join(x for x in (role.title, role.company) if x)
        for bullet in role.bullets:
            relevance = len(skills_in(bullet, facts) & wanted)
            scored.append((-relevance, order, Evidence(g, label, bullet.strip().rstrip("."))))
            order += 1
    base = len(resume.experience)
    for k, project in enumerate(resume.projects):
        tech = f", using {_join(project.technologies[:4])}" if project.technologies else ""
        text = project.description or (project.bullets[0] if project.bullets else "")
        line = f"I built {project.name}{tech}" + (f": {text.strip().rstrip('.')}" if text else "")
        relevance = len(skills_in(line, facts) & wanted)
        scored.append((-relevance, order, Evidence(base + k, project.name, line, project=True)))
        order += 1
    return [e for *_, e in sorted(scored, key=lambda t: (t[0], t[1]))]


def evidence_sentences(items: list[Evidence]) -> list[str]:
    """One sentence per role or project, in resume order, quoting the bullets."""
    groups: dict[int, list[Evidence]] = {}
    for e in items:
        groups.setdefault(e.group, []).append(e)
    out: list[str] = []
    for g in sorted(groups):
        es = groups[g]
        if es[0].project:
            out += [_sentence(e.text) for e in es]
            continue
        label = es[0].label
        verbs = [e.text for e in es if _starts_with_verb(e.text)]
        others = [e.text for e in es if not _starts_with_verb(e.text)]
        if verbs:
            lowered = [v[0].lower() + v[1:] for v in verbs]
            if len(lowered) <= 2:
                joined = " and ".join(lowered)
            else:
                joined = "; ".join(lowered[:-1]) + "; and " + lowered[-1]
            out.append(_sentence(f"As {label}, I {joined}" if label else f"I {joined}"))
        for other in others:
            out.append(_sentence(f"As {label}: {other}" if label else other))
    return out


def compose(inp: CoverLetterInput) -> CoverLetterResult:
    job, cand, resume = inp.job, inp.candidate, inp.resume
    facts = facts_from(resume, extra_skills=cand.skills)
    skills = [s for s in inp.matched_skills if facts.has_skill(s)]
    wanted = {s.casefold() for s in skills}
    used: list[str] = []

    opening = f"I am applying for the {job.title} role at {job.company_name}."
    level = LEVEL_WORDS.get(cand.seniority or "")
    role_name = cand.roles[0] if cand.roles else None
    years = (
        int(cand.years_experience) if cand.years_experience and cand.years_experience >= 1 else None
    )
    if role_name:
        who = (
            f"{level} {role_name}"
            if level and level.lower() not in role_name.lower()
            else role_name
        )
        line = f"I am a {who}" + (f" with {years}+ years of experience" if years else "")
        latest = resume.experience[0] if resume.experience else None
        if latest and latest.title and latest.company:
            verb = "currently" if latest.is_current else "most recently"
            line += f", {verb} working as {latest.title} at {latest.company}"
        opening += " " + _sentence(line)
        used.append("profile: role, level, years of experience")

    evidence = evidence_items(resume, wanted, facts)
    if skills:
        lead = (
            f"Your posting asks for {_join(skills[:4])}, and "
            f"{'these are' if len(skills[:4]) > 1 else 'this is'} part of my day-to-day work."
        )
        used.append(f"matched skills: {', '.join(skills[:4])}")
    else:
        lead = "Here is the experience I would bring to the role."
    n_evidence = min(2, len(evidence))

    focus = skills[0] if skills else None
    fit = (
        f"The {job.title} role is a strong match for the work I do best"
        + (f", particularly {focus}" if focus else "")
        + f", and I would be glad to bring that experience to {job.company_name}."
    )
    closing = (
        f"Thank you for considering my application. I would welcome the chance to talk about "
        f"how I can contribute to {job.company_name}."
    )

    def build(k: int) -> list[str]:
        middle = " ".join([lead, *evidence_sentences(evidence[:k])])
        return [opening, middle, fit, closing]

    paragraphs = build(n_evidence)
    while word_count(" ".join(paragraphs)) < MIN_WORDS and n_evidence < min(
        MAX_EVIDENCE, len(evidence)
    ):
        n_evidence += 1
        paragraphs = build(n_evidence)
    while word_count(" ".join(paragraphs)) > MAX_WORDS and n_evidence > 1:
        n_evidence -= 1
        paragraphs = build(n_evidence)
    used += [f"resume ({e.label}): {e.text}" for e in evidence[:n_evidence]]

    notes = ["The sentence about why the role fits is general; make it personal before sending."]
    words = word_count(" ".join(paragraphs))
    if words < MIN_WORDS:
        notes.append(
            f"The letter is {words} words: your resume has few details to draw on, and nothing "
            "was invented to lengthen it."
        )
    if words > MAX_WORDS:
        notes.append(f"The letter is {words} words; consider trimming it.")
    return CoverLetterResult(
        paragraphs=paragraphs,
        greeting=f"Dear {job.company_name} hiring team,",
        recipient=f"Hiring team, {job.company_name}",
        notes=notes,
        facts_used=used,
    )


def claude_facts(inp: CoverLetterInput, base: CoverLetterResult) -> dict[str, str]:
    cand = inp.candidate
    facts = {
        "level": cand.seniority,
        "years_of_experience": int(cand.years_experience) if cand.years_experience else None,
        "target_roles": list(cand.roles[:3]),
        "skills_the_job_asks_for_that_candidate_has": list(inp.matched_skills[:8]),
        "experience": [
            {
                "title": e.title,
                "company": e.company,
                "current": e.is_current,
                "bullets": e.bullets[:5],
            }
            for e in inp.resume.experience[:4]
        ],
        "projects": [
            {"name": p.name, "technologies": p.technologies, "description": p.description}
            for p in inp.resume.projects[:3]
        ],
        "draft": base.paragraphs,
    }
    job = {
        "title": inp.job.title,
        "company": inp.job.company_name,
        "requirements": list(inp.job.requirements)[:15],
    }
    return {
        "facts_json": json.dumps(facts, ensure_ascii=False),
        "job_json": json.dumps(job, ensure_ascii=False),
    }


def accept_claude(
    inp: CoverLetterInput, base: CoverLetterResult, paragraphs: list[str], model: str | None
) -> CoverLetterResult:
    """Claude's letter if it passes every check, else the rule-based one."""
    paragraphs = [p.strip() for p in paragraphs if p.strip()]
    text = "\n\n".join(paragraphs)
    facts = facts_from(inp.resume, extra_skills=inp.candidate.skills)
    years = [str(int(inp.candidate.years_experience))] if inp.candidate.years_experience else []
    problems = check_text(text, facts, allow_numbers=years)
    words = word_count(text)
    if not MIN_WORDS <= words <= MAX_WORDS:
        problems.append(f"{words} words (needs {MIN_WORDS}-{MAX_WORDS})")
    if inp.job.company_name.casefold() not in text.casefold():
        problems.append("does not name the company")
    if problems:
        base.notes.append("Claude's letter was not used: " + "; ".join(problems[:3]) + ".")
        return base
    return CoverLetterResult(
        paragraphs=paragraphs,
        greeting=base.greeting,
        recipient=base.recipient,
        method="claude",
        model=model,
        notes=["Written by Claude from your resume facts and checked against them."],
        facts_used=base.facts_used,
    )


class CoverLetterAgent(Agent):
    name = "agent_8_cover_letters"

    async def run(self, inp: CoverLetterInput, *, use_llm: bool) -> CoverLetterResult:
        base = compose(inp)
        if not (use_llm and self.llm.enabled):
            return base
        async with self.track(input_summary={"job": inp.job.title}) as run:
            values = claude_facts(inp, base)
            try:
                answer = await self.llm.structured(
                    COVER_LETTER,
                    model=self.llm.settings.claude_model_writing,
                    facts_json=values["facts_json"],
                    job_json=values["job_json"],
                )
            except LLMError as exc:
                base.notes.append(f"Claude letter skipped: {exc.message}")
                run.output_summary["error"] = exc.message
                return base
            self.record(run, COVER_LETTER.name, answer)
            result = accept_claude(inp, base, answer.output.paragraphs, answer.usage.model)
            run.output_summary["method"] = result.method
            return result


def generation_json(result: CoverLetterResult) -> dict[str, Any]:
    return {
        "facts": result.facts_used,
        "notes": result.notes,
        "recipient": result.recipient,
        "greeting": result.greeting,
    }
