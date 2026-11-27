"""Agent 9: answers to common application questions.

Every answer is built from stated facts and carries its evidence:

| key | from |
|---|---|
| why_company | the posting (company, role, the skills it asks for that you have) |
| why_qualified | profile (level, years, latest role) + resume bullets + matched skills |
| salary_expectations | settings (target / minimum, currency) + the posting's range |
| relocation | settings (willing_to_relocate) + job and profile locations |
| sponsorship | settings (requires_sponsorship) |
| work_authorization | settings (work_authorization, visa_status) |
| years_experience | profile (total years) |
| experience:<skill> | the roles whose text names the skill, and their dates |

Nothing is guessed. Where the facts are missing or the answer is a matter of
opinion (why this company), the answer is flagged `needs_review` with low
confidence and says so, instead of making something up.

Claude (optional) only polishes the two free-text answers, and a rewrite is
kept only if it adds no skill or number (`app.agents.truthfulness`).
"""

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from app.agents.agent_4_rule_filtering import matches_location
from app.agents.agent_6_resume_tailoring import LEVEL_WORDS, CandidateFacts, TailoringJob, _join
from app.agents.base import Agent
from app.agents.truthfulness import check_text, facts_from
from app.llm.client import LLMError
from app.llm.prompts.application_answers import APPLICATION_ANSWERS
from app.parsing.dates import total_months
from app.parsing.skills import AMBIGUOUS
from app.schemas.parsed_resume import ExperienceEntry, ParsedResume

MAX_SKILL_QUESTIONS = 5
MAX_MISSING_QUESTIONS = 3
POLISHED_KEYS = ("why_company", "why_qualified")


@dataclass(frozen=True)
class AnswerSettings:
    salary_min: int | None = None
    salary_target: int | None = None
    salary_currency: str = "USD"
    willing_to_relocate: bool | None = None
    requires_sponsorship: bool = False
    work_authorization: str | None = None
    visa_status: str | None = None


@dataclass(frozen=True)
class AnswerJob:
    job: TailoringJob
    location: str | None = None
    remote_type: str = "unknown"
    salary_min: int | None = None
    salary_max: int | None = None
    salary_currency: str | None = None


@dataclass
class GeneratedAnswer:
    key: str
    question: str
    answer: str
    source: str  # profile | settings | rules | llm
    confidence: float
    needs_review: bool = False
    evidence: list[dict[str, str]] = field(default_factory=list)

    def as_row(self) -> dict[str, Any]:
        data = asdict(self)
        data["question_key"] = data.pop("key")
        data["confidence"] = Decimal(str(round(self.confidence, 2)))
        return data


def _ev(source: str, fact: str) -> dict[str, str]:
    return {"source": source, "fact": fact}


def _money(value: int, currency: str) -> str:
    return f"{currency} {value:,}"


def _mentions(text: str, skill: str) -> bool:
    flags = 0 if (skill.lower() in AMBIGUOUS or len(skill) <= 2) else re.IGNORECASE
    return re.search(rf"(?<![\w+#.]){re.escape(skill)}(?![\w+#]|\.\w)", text, flags) is not None


def roles_using(resume: ParsedResume, skill: str) -> list[ExperienceEntry]:
    return [
        e
        for e in resume.experience
        if _mentions("\n".join([e.title or "", *e.bullets, *e.skills]), skill)
    ]


# ------------------------------------------------------------------ answers
def why_company(job: AnswerJob, skills: list[str]) -> GeneratedAnswer:
    j = job.job
    focus = f", especially the focus on {_join(skills[:3])}" if skills else ""
    text = (
        f"The {j.title} role at {j.company_name} lines up with the work I do best{focus}. "
        f"I want to bring that experience to {j.company_name}'s team and keep building on it."
    )
    return GeneratedAnswer(
        "why_company",
        f"Why do you want to work at {j.company_name}?",
        text,
        "rules",
        0.5,
        needs_review=True,
        evidence=[
            _ev("job", f"{j.title} at {j.company_name}"),
            *[_ev("job", f"asks for {s}") for s in skills[:3]],
            _ev("note", "Motivation is personal: add your own reason before sending."),
        ],
    )


def why_qualified(
    job: AnswerJob, cand: CandidateFacts, resume: ParsedResume, skills: list[str]
) -> GeneratedAnswer:
    parts: list[str] = []
    evidence: list[dict[str, str]] = []
    level = LEVEL_WORDS.get(cand.seniority or "")
    years = (
        int(cand.years_experience) if cand.years_experience and cand.years_experience >= 1 else None
    )
    if cand.roles:
        who = cand.roles[0]
        if level and level.lower() not in who.lower():
            who = f"{level} {who}"
        parts.append(f"I am a {who}" + (f" with {years}+ years of experience." if years else "."))
        evidence.append(
            _ev(
                "profile",
                f"role {cand.roles[0]}, level {cand.seniority}, years {cand.years_experience}",
            )
        )
    if skills:
        parts.append(f"I have worked with {_join(skills[:5])}, which this role asks for.")
        evidence += [_ev("resume", f"lists {s}") for s in skills[:5]]
    for role in resume.experience[:2]:
        if role.bullets:
            label = " at ".join(x for x in (role.title, role.company) if x)
            parts.append(f"As {label}: {role.bullets[0].rstrip('.')}.")
            evidence.append(_ev("resume", f"{label}: {role.bullets[0]}"))
    if not parts:
        return GeneratedAnswer(
            "why_qualified",
            "Why are you qualified for this role?",
            "Please describe your relevant experience here; your profile has too little detail "
            "to answer from.",
            "rules",
            0.1,
            needs_review=True,
        )
    return GeneratedAnswer(
        "why_qualified",
        "Why are you qualified for this role?",
        " ".join(parts),
        "profile",
        0.85,
        evidence=evidence,
    )


def salary_expectations(job: AnswerJob, s: AnswerSettings) -> GeneratedAnswer:
    q = "What are your salary expectations?"
    cur = s.salary_currency
    target = s.salary_target if s.salary_target is not None else s.salary_min
    if target is None:
        return GeneratedAnswer(
            "salary_expectations",
            q,
            "I would like to learn more about the role and its scope before discussing salary.",
            "rules",
            0.2,
            needs_review=True,
            evidence=[_ev("settings", "no salary target or minimum set")],
        )
    evidence = []
    if s.salary_target is not None:
        text = f"My target base salary is {_money(s.salary_target, cur)} per year"
        evidence.append(_ev("settings", f"salary_target {s.salary_target} {cur}"))
        if s.salary_min is not None and s.salary_min < s.salary_target:
            text += f", and I would consider offers from {_money(s.salary_min, cur)}"
            evidence.append(_ev("settings", f"salary_min {s.salary_min} {cur}"))
    else:
        text = f"I am looking for a base salary of at least {_money(target, cur)} per year"
        evidence.append(_ev("settings", f"salary_min {target} {cur}"))
    lo, hi = job.salary_min, job.salary_max
    same_currency = (job.salary_currency or cur) == cur
    if same_currency and lo is not None and hi is not None and lo <= target <= hi:
        text += ", which is within the range in your posting"
        evidence.append(_ev("job", f"posted range {lo}-{hi} {cur}"))
    text += ", depending on the full compensation package."
    return GeneratedAnswer("salary_expectations", q, text, "settings", 0.95, evidence=evidence)


def relocation(job: AnswerJob, s: AnswerSettings, profile_location: str | None) -> GeneratedAnswer:
    q = "Are you willing to relocate?"
    if job.remote_type == "remote":
        return GeneratedAnswer(
            "relocation",
            q,
            "This role is remote, so relocation is not needed.",
            "rules",
            0.9,
            evidence=[_ev("job", "remote role")],
        )
    if profile_location and job.location and matches_location(job.location, profile_location):
        return GeneratedAnswer(
            "relocation",
            q,
            f"I already live in {profile_location}, so I would not need to relocate.",
            "profile",
            0.85,
            evidence=[
                _ev("profile", f"location {profile_location}"),
                _ev("job", f"location {job.location}"),
            ],
        )
    if s.willing_to_relocate is None:
        return GeneratedAnswer(
            "relocation",
            q,
            "Please answer this yourself: your settings do not say whether you "
            "are willing to relocate.",
            "rules",
            0.1,
            needs_review=True,
            evidence=[_ev("settings", "willing_to_relocate not set")],
        )
    where = f" to {job.location}" if job.location else ""
    text = (
        f"Yes, I am willing to relocate{where}."
        if s.willing_to_relocate
        else "No, I am not able to relocate for this role."
    )
    return GeneratedAnswer(
        "relocation",
        q,
        text,
        "settings",
        0.95,
        evidence=[_ev("settings", f"willing_to_relocate {s.willing_to_relocate}")],
    )


def sponsorship(s: AnswerSettings) -> GeneratedAnswer:
    q = "Will you now or in the future require visa sponsorship?"
    text = (
        "Yes, I will require visa sponsorship."
        if s.requires_sponsorship
        else "No, I do not require visa sponsorship."
    )
    if s.visa_status and s.requires_sponsorship:
        text = text[:-1] + f" (current status: {s.visa_status})."
    # requires_sponsorship defaults to false: with no authorization stated either,
    # the "No" may just be the default.
    unsure = not s.requires_sponsorship and not s.work_authorization
    return GeneratedAnswer(
        "sponsorship",
        q,
        text,
        "settings",
        0.6 if unsure else 0.95,
        needs_review=unsure,
        evidence=[_ev("settings", f"requires_sponsorship {s.requires_sponsorship}")]
        + (
            [_ev("note", "Confirm this: work authorization is not set in your settings.")]
            if unsure
            else []
        ),
    )


def work_authorization(s: AnswerSettings) -> GeneratedAnswer:
    q = "What is your work authorization status?"
    if not s.work_authorization:
        return GeneratedAnswer(
            "work_authorization",
            q,
            "Please answer this yourself: your work authorization is not set in your settings.",
            "rules",
            0.1,
            needs_review=True,
            evidence=[_ev("settings", "work_authorization not set")],
        )
    text = s.work_authorization.rstrip(".") + "."
    if s.visa_status:
        text += f" Visa status: {s.visa_status.rstrip('.')}."
    return GeneratedAnswer(
        "work_authorization",
        q,
        text,
        "settings",
        0.95,
        evidence=[_ev("settings", f"work_authorization {s.work_authorization}")],
    )


def years_experience(cand: CandidateFacts) -> GeneratedAnswer:
    q = "How many years of professional experience do you have?"
    if cand.years_experience is None:
        return GeneratedAnswer(
            "years_experience",
            q,
            "Please answer this yourself: your profile has no dated experience.",
            "rules",
            0.1,
            needs_review=True,
        )
    y = cand.years_experience
    shown = f"{y:g}" if y != int(y) else str(int(y))
    return GeneratedAnswer(
        "years_experience",
        q,
        f"I have {shown} years of professional experience.",
        "profile",
        0.9,
        evidence=[_ev("profile", f"years_experience {y} (from role dates)")],
    )


def skill_experience(
    skill: str, resume: ParsedResume, listed: bool, today: date | None
) -> GeneratedAnswer:
    q = f"How many years of experience do you have with {skill}?"
    roles = roles_using(resume, skill)
    if roles:
        months = total_months([(r.start_date, r.end_date, r.is_current) for r in roles], today)
        labels = [" at ".join(x for x in (r.title, r.company) if x) for r in roles]
        evidence = [_ev("resume", f"{label} mentions {skill}") for label in labels]
        if months:
            years = round(months / 12, 1)
            shown = f"{years:g}"
            text = (
                f"About {shown} year{'s' if years != 1 else ''}: I have used {skill} "
                f"in {len(roles)} role{'s' if len(roles) != 1 else ''} ({'; '.join(labels)})."
            )
            return GeneratedAnswer(
                f"experience:{skill}", q, text, "profile", 0.75, evidence=evidence
            )
        text = f"I have used {skill} in {'; '.join(labels)}."
        return GeneratedAnswer(
            f"experience:{skill}",
            q,
            text,
            "profile",
            0.5,
            needs_review=True,
            evidence=[*evidence, _ev("note", "role dates missing")],
        )
    if listed:
        return GeneratedAnswer(
            f"experience:{skill}",
            q,
            f"{skill} is among my skills; please add how long you have "
            "used it, since your resume does not tie it to a specific role.",
            "rules",
            0.3,
            needs_review=True,
            evidence=[_ev("resume", f"lists {skill}")],
        )
    return GeneratedAnswer(
        f"experience:{skill}",
        q,
        f"My resume does not list experience with {skill}.",
        "rules",
        0.3,
        needs_review=True,
        evidence=[
            _ev("resume", f"{skill} not mentioned"),
            _ev("note", "If you have used it, update your resume and regenerate."),
        ],
    )


def generate_answers(
    resume: ParsedResume,
    cand: CandidateFacts,
    job: AnswerJob,
    settings: AnswerSettings,
    matched: list[str],
    missing: list[str],
    *,
    profile_location: str | None = None,
    required: list[str] | None = None,
    today: date | None = None,
) -> list[GeneratedAnswer]:
    facts = facts_from(resume, extra_skills=cand.skills)
    skills = [s for s in matched if facts.has_skill(s)]
    req = {s.casefold() for s in (required if required is not None else matched + missing)}
    answers = [
        why_company(job, skills),
        why_qualified(job, cand, resume, skills),
        salary_expectations(job, settings),
        relocation(job, settings, profile_location),
        sponsorship(settings),
        work_authorization(settings),
        years_experience(cand),
    ]
    asked = [s for s in skills if s.casefold() in req][:MAX_SKILL_QUESTIONS]
    for skill in asked:
        answers.append(skill_experience(skill, resume, True, today))
    for skill in [s for s in missing if s.casefold() in req][:MAX_MISSING_QUESTIONS]:
        answers.append(skill_experience(skill, resume, facts.has_skill(skill), today))
    return answers


def apply_polish(
    answers: list[GeneratedAnswer],
    polished: dict[str, str],
    resume: ParsedResume,
    cand: CandidateFacts,
) -> list[str]:
    """Replace polishable answers with Claude's versions that pass the checks.
    Returns the problems of the rejected ones."""
    facts = facts_from(resume, extra_skills=cand.skills)
    years = [str(int(cand.years_experience))] if cand.years_experience else []
    rejected: list[str] = []
    for a in answers:
        new = polished.get(a.key, "").strip()
        if a.key not in POLISHED_KEYS or not new or new == a.answer:
            continue
        problems = check_text(new, facts, allow_numbers=years)
        if len(new) > 1500:
            problems.append("too long")
        if problems:
            rejected.append(f"{a.key}: {'; '.join(problems)}")
            continue
        a.answer, a.source = new, "llm"
        a.evidence.append(_ev("note", "Reworded by Claude; checked against your resume."))
    return rejected


class ApplicationAnswersAgent(Agent):
    name = "agent_9_application_answers"

    async def run(
        self,
        answers: list[GeneratedAnswer],
        resume: ParsedResume,
        cand: CandidateFacts,
        job: TailoringJob,
        *,
        use_llm: bool,
    ) -> list[str]:
        """Polish answers in place with Claude; returns notes."""
        if not (use_llm and self.llm.enabled):
            return []
        drafts = [
            {"key": a.key, "question": a.question, "answer": a.answer}
            for a in answers
            if a.key in POLISHED_KEYS
        ]
        async with self.track(input_summary={"job": job.title}) as run:
            try:
                result = await self.llm.structured(
                    APPLICATION_ANSWERS,
                    model=self.llm.settings.claude_model_writing,
                    facts_json=json.dumps(
                        {
                            "skills": list(cand.skills),
                            "level": cand.seniority,
                            "years": cand.years_experience,
                            "roles": list(cand.roles[:3]),
                            "experience": [
                                {"title": e.title, "company": e.company, "bullets": e.bullets[:4]}
                                for e in resume.experience[:3]
                            ],
                        },
                        ensure_ascii=False,
                    ),
                    drafts_json=json.dumps(drafts, ensure_ascii=False),
                    job_json=json.dumps(
                        {
                            "title": job.title,
                            "company": job.company_name,
                            "requirements": list(job.requirements)[:10],
                        },
                        ensure_ascii=False,
                    ),
                )
            except LLMError as exc:
                run.output_summary["error"] = exc.message
                return [f"Claude polishing skipped: {exc.message}"]
            self.record(run, APPLICATION_ANSWERS.name, result)
            rejected = apply_polish(
                answers, {a.key: a.answer for a in result.output.answers}, resume, cand
            )
            run.output_summary["rejected"] = rejected
            return [f"Claude's version of {r} was not used." for r in rejected]
