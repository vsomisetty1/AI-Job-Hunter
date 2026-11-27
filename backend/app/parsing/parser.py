"""Deterministic resume parser.

`parse_document(doc)` turns extracted lines into a `ParsedResume` and scores
how much each section can be trusted. `weak_sections(result)` names the
sections worth sending to Claude; everything else never leaves the machine.
"""

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, field, replace

from app.documents.sandbox import ExtractedDocument, ExtractedLine
from app.parsing import entries
from app.parsing.contact import extract_contact
from app.parsing.sections import Section, split_sections
from app.parsing.skills import dedupe_skills, find_skills
from app.schemas.parsed_resume import (
    OtherSection,
    ParsedResume,
    ParseMeta,
    SectionName,
    SectionScore,
)

# Sections whose score below this threshold makes them candidates for Claude.
WEAK_THRESHOLD = 0.6
# Below this overall confidence, the whole document is sent instead.
WHOLE_DOCUMENT_THRESHOLD = 0.35


@dataclass
class ParseResult:
    resume: ParsedResume
    sections: dict[str, list[str]]  # canonical section -> raw lines (for LLM input)
    scores: dict[str, float] = field(default_factory=dict)


def _score_contact(r: ParsedResume) -> float:
    c = r.contact
    return (0.5 if c.name else 0) + (0.3 if c.email else 0) + (0.2 if c.phone or c.linkedin else 0)


def _score_experience(r: ParsedResume, present: bool) -> float:
    if not r.experience:
        return 0.0 if present else 1.0
    complete = [e for e in r.experience if e.title and e.company and (e.start_date or e.end_date)]
    return len(complete) / len(r.experience)


def _score_education(r: ParsedResume, present: bool) -> float:
    if not r.education:
        return 0.0 if present else 1.0
    good = [e for e in r.education if e.institution and (e.degree or e.end_date)]
    return len(good) / len(r.education)


def _score_list(items: Sequence[object], present: bool) -> float:
    return 1.0 if items or not present else 0.0


_CID = re.compile(r"\(cid:\d+\)")
_INVISIBLE = re.compile(r"[\u200b-\u200f\u2028-\u202e\u2060-\u2064\ufeff\uf0b7\uf0a7\uf076\uf0d8]")


def normalize_line(text: str) -> str:
    """Clean extraction artefacts. Unmapped glyphs at line start are bullets."""
    text = unicodedata.normalize("NFKC", text)
    text = _CID.sub("\u2022", text, count=1) if text.lstrip().startswith("(cid:") else text
    text = _CID.sub("", text)
    text = _INVISIBLE.sub("\u2022" if text[:1] in "\uf0b7\uf0a7" else "", text)
    return re.sub(r"[ \t]+", " ", text).strip()


def _clean_lines(lines: list[ExtractedLine]) -> list[ExtractedLine]:
    out = []
    for line in lines:
        text = normalize_line(line.text)
        if text:
            out.append(replace(line, text=text))
    return out


def parse_document(doc: ExtractedDocument) -> ParseResult:
    doc = replace(doc, lines=_clean_lines(doc.lines))
    sections = split_sections(doc.lines)
    by_name: dict[str, list[Section]] = {}
    for s in sections:
        by_name.setdefault(s.name, []).append(s)

    def lines_of(name: str) -> list[str]:
        return [t for s in by_name.get(name, []) for t in s.texts]

    header = [ln for s in by_name.get("header", []) for ln in s.lines]
    r = ParsedResume()
    r.contact = extract_contact(header or doc.lines[:8], doc.text, doc.links)

    summary_lines = lines_of("summary")
    if summary_lines:
        r.summary = " ".join(entries.strip_bullet(t) for t in summary_lines).strip() or None
    r.experience = entries.parse_experience(lines_of("experience"))
    r.education = entries.parse_education(lines_of("education"))
    explicit_skills, r.skill_groups = entries.parse_skills(lines_of("skills"))
    r.certifications = entries.parse_certifications(lines_of("certifications"))
    r.projects = entries.parse_projects(lines_of("projects"))
    r.publications = entries.parse_publications(lines_of("publications"))
    r.awards = entries.parse_awards(lines_of("awards"))
    r.languages = entries.parse_languages(lines_of("languages"))
    for name in ("volunteer", "interests", "references", "other"):
        for s in by_name.get(name, []):
            if s.texts:
                r.other_sections.append(
                    OtherSection(title=s.heading or name.title(), lines=s.texts)
                )

    # All skills: the explicit list first, then skills mined from experience/projects.
    mined = [sk for e in r.experience for sk in e.skills] + [
        sk for p in r.projects for sk in p.technologies
    ]
    if r.summary:
        mined += find_skills(r.summary)
    r.skills = dedupe_skills(explicit_skills + mined)

    scores: dict[str, float] = {
        "contact": _score_contact(r),
        "experience": _score_experience(r, "experience" in by_name),
        "education": _score_education(r, "education" in by_name),
        "skills": _score_list(r.skills, "skills" in by_name),
        "certifications": _score_list(r.certifications, "certifications" in by_name),
        "projects": _score_list(r.projects, "projects" in by_name),
        "publications": _score_list(r.publications, "publications" in by_name),
        "awards": _score_list(r.awards, "awards" in by_name),
    }
    found_core = {"experience", "education", "skills"} & set(by_name)
    weights = {"contact": 2, "experience": 3, "education": 1.5, "skills": 1.5}
    overall = sum(scores[k] * w for k, w in weights.items()) / sum(weights.values())
    if not found_core:
        overall *= 0.4  # no recognisable structure: probably an unusual layout
    warnings = []
    if not found_core:
        warnings.append("No standard resume sections were recognised.")
    if not r.contact.name:
        warnings.append("Could not find the candidate's name.")
    if len(doc.text.strip()) < 200:
        warnings.append("Very little text was extracted; the file may be a scanned image.")

    r.meta = ParseMeta(
        method="deterministic",
        confidence=round(overall, 3),
        section_confidence=[SectionScore(section=k, score=round(v, 3)) for k, v in scores.items()],
        warnings=warnings,
    )
    raw = {name: lines_of(name) for name in by_name}
    return ParseResult(resume=r, sections=raw, scores=scores)


def weak_sections(result: ParseResult) -> list[SectionName] | None:
    """Sections to send to Claude, or None for "send the whole document".

    Only sections that exist in the document (or contact details) qualify, so
    a resume that simply has no publications never triggers a call.
    """
    if result.resume.meta.confidence < WHOLE_DOCUMENT_THRESHOLD:
        return None
    weak: list[SectionName] = []
    candidates: tuple[SectionName, ...] = (
        "contact", "experience", "education", "certifications", "projects", "publications",
        "awards",
    )  # fmt: skip
    for name in candidates:
        present = name == "contact" or name in result.sections
        if present and result.scores.get(name, 1.0) < WEAK_THRESHOLD:
            weak.append(name)
    return weak
