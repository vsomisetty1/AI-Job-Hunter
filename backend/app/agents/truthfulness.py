"""Truthfulness guard for generated application material (Agents 6, 8, 9).

Generated text may reword, reorder and emphasise what the resume says. It may
not add technologies, numbers (metrics, years, team sizes), employers, titles
or dates. This module states what the candidate's material contains (`Facts`)
and checks text and tailored resumes against it.

* `facts_from(resume, extra_text=...)` collects the skills the resume names
  (listed skills plus skills mentioned in any text) and every number in it.
  `extra_text` adds trusted context that may be quoted, such as the job
  posting's company name; skills that appear only in the job posting are NOT
  facts about the candidate.
* `check_text(text, facts)` returns violations: skills or numbers in `text`
  that the facts do not contain.
* `check_tailored(original, tailored)` also locks the structure: same roles
  with the same employer, title, location and dates, same education,
  certifications and contact details, and no skill the original lacks.

Deterministic generators only reuse resume text, so they pass by design; the
checks matter for Claude's output, which is dropped when it fails them.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass, field

from app.parsing.skills import AMBIGUOUS, find_skills, normalize_skill
from app.schemas.parsed_resume import ParsedResume

# Numbers as written: 40%, 1,200, 3.5, $2M, 10x. Years like 2021 count too.
_NUMBER = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?")


def _norm_number(raw: str) -> str:
    return raw.replace(",", "").rstrip(".")


def numbers_in(text: str) -> set[str]:
    return {_norm_number(m) for m in _NUMBER.findall(text or "")}


def resume_text(resume: ParsedResume) -> str:
    """All free text of a resume, one item per line."""
    parts: list[str] = [resume.summary or ""]
    for e in resume.experience:
        parts += [e.title or "", e.company or "", e.location or "", *e.bullets, *e.skills]
        parts += [e.start_date or "", e.end_date or ""]
    for ed in resume.education:
        parts += [ed.institution or "", ed.degree or "", ed.field_of_study or "", *ed.honors]
        parts += [ed.start_date or "", ed.end_date or "", ed.gpa or ""]
    parts += resume.skills
    for g in resume.skill_groups:
        parts += [g.name, *g.skills]
    for c in resume.certifications:
        parts += [c.name, c.issuer or ""]
    for p in resume.projects:
        parts += [p.name, p.description or "", *p.technologies, *p.bullets]
    for pub in resume.publications:
        parts += [pub.title, pub.venue or ""]
    for a in resume.awards:
        parts += [a.title, a.issuer or "", a.description or ""]
    for o in resume.other_sections:
        parts += [o.title, *o.lines]
    return "\n".join(p for p in parts if p)


@dataclass(frozen=True)
class Facts:
    skills: frozenset[str]  # casefolded canonical names
    numbers: frozenset[str]
    listed_skills: tuple[str, ...] = field(default=())  # as the candidate wrote them

    def has_skill(self, skill: str) -> bool:
        return normalize_skill(skill).casefold() in self.skills


def facts_from(
    resume: ParsedResume,
    *,
    extra_skills: Iterable[str] = (),
    extra_text: Iterable[str] = (),
) -> Facts:
    """Facts of a resume. `extra_skills`: skills the candidate states elsewhere
    (their profile). `extra_text`: trusted text whose numbers may be quoted
    (e.g. the posting's salary range is not about the candidate, so it is
    not passed here)."""
    text = resume_text(resume)
    listed = [s for s in [*resume.skills, *extra_skills] if s.strip()]
    for e in resume.experience:
        listed += e.skills
    for g in resume.skill_groups:
        listed += g.skills
    for p in resume.projects:
        listed += p.technologies
    skills = {normalize_skill(s).casefold() for s in listed}
    skills |= {s.casefold() for s in find_skills(text)}
    numbers = numbers_in(text)
    for extra in extra_text:
        numbers |= numbers_in(extra)
    return Facts(frozenset(skills), frozenset(numbers), tuple(dict.fromkeys(listed)))


def skills_in(text: str, facts: Facts) -> set[str]:
    """Known skills named in `text`: the taxonomy's unambiguous names, plus the
    candidate's own skills (ambiguous short ones only with matching case)."""
    found = {s.casefold() for s in find_skills(text)}
    for skill in facts.listed_skills:
        canonical = normalize_skill(skill)
        flags = 0 if (skill.lower() in AMBIGUOUS or len(skill) <= 2) else re.IGNORECASE
        if re.search(rf"(?<![\w+#.]){re.escape(skill)}(?![\w+#]|\.\w)", text, flags):
            found.add(canonical.casefold())
    return found


def check_text(text: str, facts: Facts, *, allow_numbers: Iterable[str] = ()) -> list[str]:
    """Violations: skills or numbers in `text` that are not in the facts."""
    problems = [
        f"mentions '{normalize_skill(s)}', which the resume does not"
        for s in sorted(skills_in(text, facts) - facts.skills)
    ]
    allowed = facts.numbers | {_norm_number(n) for n in allow_numbers}
    problems += [
        f"uses the number {n}, which the resume does not"
        for n in sorted(numbers_in(text) - allowed)
    ]
    return problems


def _role_key(e: object) -> tuple[object, ...]:
    return tuple(
        getattr(e, f) for f in ("title", "company", "location", "start_date", "end_date",
                                "is_current")
    )  # fmt: skip


def check_tailored(
    original: ParsedResume,
    tailored: ParsedResume,
    *,
    extra_skills: Iterable[str] = (),
    allow_numbers: Iterable[str] = (),
) -> list[str]:
    """Everything that makes `tailored` claim more than `original`.

    `extra_skills`: skills from the candidate's profile; `allow_numbers`:
    computed facts such as total years of experience."""
    allow = list(allow_numbers)
    problems: list[str] = []
    if tailored.contact != original.contact:
        problems.append("contact details changed")
    if [_role_key(e) for e in tailored.experience] != [_role_key(e) for e in original.experience]:
        problems.append("roles changed (employer, title, location, dates or order)")
    if tailored.education != original.education:
        problems.append("education changed")
    if tailored.certifications != original.certifications:
        problems.append("certifications changed")
    if {p.name for p in tailored.projects} != {p.name for p in original.projects}:
        problems.append("projects added or removed")
    facts = facts_from(original, extra_skills=extra_skills)
    for skill in tailored.skills:
        if not facts.has_skill(skill):
            problems.append(f"adds the skill '{skill}'")
    for i, (new, old) in enumerate(zip(tailored.experience, original.experience, strict=False)):
        if len(new.bullets) > len(old.bullets):
            problems.append(f"role {i + 1} has more bullets than the original")
        # A reworded bullet may only reuse numbers from the same role's bullets.
        role_facts = Facts(
            facts.skills, frozenset(numbers_in("\n".join(old.bullets))), facts.listed_skills
        )
        for bullet in new.bullets:
            if bullet not in old.bullets:
                problems += [f"role {i + 1}: {p}" for p in check_text(bullet, role_facts)]
    if tailored.summary and tailored.summary != original.summary:
        problems += [
            f"summary: {p}" for p in check_text(tailored.summary, facts, allow_numbers=allow)
        ]
    return problems
