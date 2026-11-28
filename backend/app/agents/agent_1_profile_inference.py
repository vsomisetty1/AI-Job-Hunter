"""Agent 1: candidate profile generation.

1. Deterministic profile from the parsed resume: years of experience (overlaps
   merged), career history, seniority heuristic, education and certification
   summaries, skills. Always available, no tokens.
2. With Claude: profile inference and career analysis run in parallel on a
   compact, PII-free JSON of the resume (no name, contact details or links);
   skill extraction runs only when the deterministic skill list is short.
   Any Claude failure keeps the deterministic result and records a warning.
"""

import asyncio
import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from app.agents.base import Agent
from app.llm.client import LLMError, LLMResult
from app.llm.prompts import CAREER_ANALYSIS, PROFILE_INFERENCE, SKILL_EXTRACTION
from app.parsing.dates import total_months
from app.parsing.skills import dedupe_skills
from app.schemas.candidate_profile import (
    CareerAnalysisOutput,
    CareerHistoryItem,
    InferenceData,
    ProfileData,
    ProfileInferenceOutput,
    SkillExtractionOutput,
)
from app.schemas.parsed_resume import ParsedResume

logger = logging.getLogger(__name__)

MIN_SKILLS_BEFORE_EXTRACTION = 8
MAX_BULLETS_PER_ROLE = 6  # inference needs the gist, not every bullet

_TITLE_SENIORITY = [
    (("intern", "internship", "trainee", "apprentice"), "intern"),
    (("chief", "cto", "ceo", "cfo", "coo", "vp", "vice president", "president"), "executive"),
    (("director",), "director"),
    (("head of", "manager"), "manager"),
    (("principal",), "principal"),
    (("staff",), "staff"),
    (("lead",), "lead"),
    (("senior", "sr.", "sr "), "senior"),
    (("junior", "jr.", "jr ", "entry", "graduate", "associate"), "junior"),
]


# Employment arrangements written next to a title: part of the resume, not of the
# role someone would search for ("Platform Engineer (Contract)").
_ARRANGEMENT = re.compile(
    r"\s*(?:[(\[]\s*(?:contingent|contract(?:or)?|consultant|temp(?:orary)?|part[- ]time|"
    r"full[- ]time|freelance|remote|hybrid|on[- ]site|c2c|w-?2|1099|via [^)\]]+)[^)\]]*[)\]]"
    r"|\s+[-\u2013\u2014|]\s*(?:contract(?:or)?|contingent|temp(?:orary)?|part[- ]time)\s*$)",
    re.IGNORECASE,
)


def role_name(title: str) -> str:
    """A title without employment-arrangement qualifiers."""
    return " ".join(_ARRANGEMENT.sub("", title).split()) or title


@dataclass
class ProfileBuild:
    """Everything profile generation produces; applied to the DB by the service."""

    columns: dict[str, Any]
    profile: ProfileData
    inference: InferenceData
    llm_errors: list[str] = field(default_factory=list)


def seniority_from(title: str | None, years: float | None) -> str | None:
    t = f" {(title or '').lower()} "
    for words, level in _TITLE_SENIORITY:
        if any(w in t for w in words):
            return level
    if years is None:
        return None
    return "entry" if years < 1 else "junior" if years < 3 else "mid" if years < 6 else "senior"


def _degree_rank(degree: str | None) -> int:
    d = (degree or "").lower().replace(".", "").replace(" ", "")
    if d.startswith(("phd", "doctor", "md", "jd")):
        return 4
    if d.startswith(("master", "ms", "ma", "mba", "msc", "meng", "mtech", "me")):
        return 3
    if d.startswith(("bachelor", "bs", "ba", "bsc", "beng", "btech", "be")):
        return 2
    return 1 if d else 0


def deterministic_profile(parsed: ParsedResume, today: date | None = None) -> ProfileBuild:
    exp = parsed.experience
    months = total_months([(e.start_date, e.end_date, e.is_current) for e in exp], today)
    years = round(months / 12, 1) if months else None

    history = []
    for e in exp:
        m = total_months([(e.start_date, e.end_date, e.is_current)], today) or None
        history.append(
            CareerHistoryItem(
                title=e.title,
                company=e.company,
                start_date=e.start_date,
                end_date=e.end_date,
                is_current=e.is_current,
                duration_months=m,
            )  # fmt: skip
        )
    latest = exp[0].title if exp else None

    titles: list[str] = []
    for e in exp:
        name = role_name(e.title) if e.title else None
        if name and name.lower() not in {t.lower() for t in titles}:
            titles.append(name)

    edu_summary = None
    if parsed.education:
        best = max(parsed.education, key=lambda e: _degree_rank(e.degree))
        bits = [b for b in (best.degree, best.field_of_study) if b]
        edu_summary = " in ".join(bits) if bits else "Studied"
        if best.institution:
            edu_summary += f", {best.institution}"
        if best.end_date:
            edu_summary += f" ({best.end_date[:4]})"
    cert_summary = (
        ", ".join(c.name for c in parsed.certifications[:5])
        + (f" and {len(parsed.certifications) - 5} more" if len(parsed.certifications) > 5 else "")
        if parsed.certifications
        else None
    )
    headline = None
    if latest:
        whole = int(years) if years is not None and years >= 1 else None
        headline = role_name(latest) + (f" with {whole}+ years of experience" if whole else "")

    seniority = seniority_from(latest, years)
    columns = {
        "full_name": parsed.contact.name,
        "email": parsed.contact.email,
        "phone": parsed.contact.phone,
        "location": parsed.contact.location,
        "linkedin_url": parsed.contact.linkedin,
        "portfolio_url": parsed.contact.portfolio or parsed.contact.github,
        "seniority": seniority,
        "years_experience": Decimal(str(years)) if years is not None else None,
        "primary_roles": titles[:5],
        "related_roles": [],
        "industries": [],
        "skills": dedupe_skills(parsed.skills),
    }
    profile = ProfileData(
        headline=headline,
        summary=parsed.summary,
        career_history=history,
        skill_groups=parsed.skill_groups,
        education=parsed.education,
        education_summary=edu_summary,
        certifications=parsed.certifications,
        certification_summary=cert_summary,
        projects=parsed.projects,
        publications=parsed.publications,
        awards=parsed.awards,
        languages=parsed.languages,
    )
    return ProfileBuild(columns, profile, InferenceData(source="deterministic"))


def compact_resume(parsed: ParsedResume) -> str:
    """Token-lean, PII-free JSON for Claude (no name, contact details or links)."""
    data: dict[str, Any] = {
        "summary": parsed.summary,
        "experience": [
            {
                "title": e.title,
                "company": e.company,
                "start": e.start_date,
                "end": "present" if e.is_current else e.end_date,
                "bullets": e.bullets[:MAX_BULLETS_PER_ROLE],
            }
            for e in parsed.experience
        ],
        "education": [
            {
                "degree": e.degree,
                "field": e.field_of_study,
                "institution": e.institution,
                "end": e.end_date,
            }  # fmt: skip
            for e in parsed.education
        ],
        "skills": parsed.skills,
        "certifications": [c.name for c in parsed.certifications],
        "projects": [
            {"name": p.name, "description": p.description, "tech": p.technologies}
            for p in parsed.projects
        ],  # fmt: skip
        "awards": [a.title for a in parsed.awards],
        "publications": [p.title for p in parsed.publications],
    }

    def prune(node: Any) -> Any:
        if isinstance(node, dict):
            return {
                k: v
                for k, v in ((k, prune(v)) for k, v in node.items())
                if v not in (None, [], {}, "")
            }
        if isinstance(node, list):
            return [v for v in (prune(v) for v in node) if v not in (None, [], {}, "")]
        return node

    return json.dumps(prune(data), separators=(",", ":"), ensure_ascii=False, sort_keys=True)


class ProfileInferenceAgent(Agent):
    name = "agent_1_profile_inference"

    async def run(
        self,
        parsed: ParsedResume,
        *,
        use_llm: bool,
        profile_id: uuid.UUID | None = None,
        today: date | None = None,
    ) -> ProfileBuild:
        async with self.track(
            input_summary={
                "profile_id": str(profile_id) if profile_id else None,
                "use_llm": use_llm,
            }
        ) as run:
            build = deterministic_profile(parsed, today)
            if not (use_llm and self.llm.enabled):
                run.output_summary["source"] = "deterministic"
                return build

            resume_json = compact_resume(parsed)
            facts = json.dumps(
                {
                    "years_of_experience": float(build.columns["years_experience"] or 0),
                    "estimated_seniority_from_title": build.columns["seniority"],
                    "today": (today or date.today()).isoformat(),
                },
                sort_keys=True,
            )
            calls: dict[str, Any] = {
                "inference": self.llm.structured(
                    PROFILE_INFERENCE, facts=facts, resume_json=resume_json
                ),
                "career": self.llm.structured(
                    CAREER_ANALYSIS, facts=facts, resume_json=resume_json
                ),
            }
            bullets = [b for e in parsed.experience for b in e.bullets]
            if len(build.columns["skills"]) < MIN_SKILLS_BEFORE_EXTRACTION and (
                bullets or parsed.projects
            ):
                text = "\n".join(bullets + [p.description or p.name for p in parsed.projects])
                calls["skills"] = self.llm.structured(
                    SKILL_EXTRACTION, known=", ".join(build.columns["skills"]) or "none", text=text
                )
            results = dict(
                zip(
                    calls,
                    await asyncio.gather(*calls.values(), return_exceptions=True),
                    strict=True,
                )
            )

            for key, res in results.items():
                if isinstance(res, LLMError):
                    build.llm_errors.append(f"{key}: {res.message}")
                    build.inference.warnings.append(f"AI {key} unavailable: {res.message}")
                elif isinstance(res, BaseException):
                    raise res
                else:
                    prompt = {"inference": PROFILE_INFERENCE, "career": CAREER_ANALYSIS,
                              "skills": SKILL_EXTRACTION}[key].name  # fmt: skip
                    self.record(run, prompt, res)

            self._apply(build, results)
            run.output_summary.update(
                {"source": build.inference.source, "errors": build.llm_errors}
            )
            return build

    @staticmethod
    def _apply(build: ProfileBuild, results: dict[str, Any]) -> None:
        inference = results.get("inference")
        if isinstance(inference, LLMResult):
            out: ProfileInferenceOutput = inference.output
            build.columns.update(
                seniority=out.seniority,
                primary_roles=list(dict.fromkeys(out.inferred_roles))[:8],
                related_roles=[r.title for r in out.transferable_roles][:8],
                industries=list(dict.fromkeys(out.industries))[:10],
            )
            build.profile.headline = out.headline or build.profile.headline
            build.profile.education_summary = (
                out.education_summary or build.profile.education_summary
            )
            build.profile.certification_summary = (
                out.certification_summary or build.profile.certification_summary
            )
            build.inference.source = "llm"
            build.inference.model = inference.usage.model
            build.inference.seniority_rationale = out.seniority_rationale
            build.inference.transferable_roles = out.transferable_roles[:8]
        career = results.get("career")
        if isinstance(career, LLMResult):
            analysis: CareerAnalysisOutput = career.output
            build.inference.career_analysis = analysis
        skills = results.get("skills")
        if isinstance(skills, LLMResult):
            extracted: SkillExtractionOutput = skills.output
            build.inference.extracted_skills = extracted
            build.columns["skills"] = dedupe_skills(
                [*build.columns["skills"], *extracted.technical, *extracted.tools]
            )
