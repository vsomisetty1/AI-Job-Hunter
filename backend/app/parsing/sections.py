"""Split resume lines into sections by detecting headings."""

import re
import statistics
from dataclasses import dataclass, field

from rapidfuzz import fuzz, process

from app.documents.sandbox import ExtractedLine
from app.parsing.contact import looks_like_name

SECTION_ALIASES: dict[str, list[str]] = {
    "summary": [
        "summary", "professional summary", "profile", "professional profile", "about me",
        "about", "objective", "career objective", "career summary", "overview", "introduction",
        "executive summary", "personal statement",
    ],
    "experience": [
        "experience", "work experience", "professional experience", "employment",
        "employment history", "work history", "career history", "relevant experience",
        "professional background", "positions held", "industry experience",
    ],
    "education": [
        "education", "academic background", "education and training", "academics",
        "academic qualifications", "qualifications", "education & training",
    ],
    "skills": [
        "skills", "technical skills", "core skills", "key skills", "core competencies",
        "competencies", "technologies", "tools", "skills and tools", "tech stack",
        "skills & tools", "areas of expertise", "expertise", "technical proficiencies",
        "skills & expertise", "skills and expertise",
    ],
    "certifications": [
        "certifications", "certificates", "licenses", "licenses and certifications",
        "licenses & certifications", "certifications and licenses", "professional certifications",
        "accreditations", "credentials",
    ],
    "projects": ["projects", "personal projects", "selected projects", "key projects",
                 "side projects", "open source", "portfolio"],
    "publications": ["publications", "papers", "research", "selected publications",
                     "research and publications", "patents", "talks", "presentations"],
    "awards": ["awards", "honors", "honours", "awards and honors", "honors and awards",
               "achievements", "accomplishments", "recognition", "awards & honors"],
    "languages": ["languages", "spoken languages", "language skills"],
    "volunteer": ["volunteer", "volunteering", "volunteer experience", "community involvement",
                  "leadership", "leadership and activities", "activities", "extracurricular activities"],
    "interests": ["interests", "hobbies", "hobbies and interests"],
    "references": ["references"],
}  # fmt: skip

_ALIAS_TO_SECTION = {a: s for s, aliases in SECTION_ALIASES.items() for a in aliases}
_NORMALIZE = re.compile(r"[^a-z& ]+")


@dataclass
class Section:
    name: str  # canonical name, or "header" for lines before the first heading
    heading: str | None
    lines: list[ExtractedLine] = field(default_factory=list)

    @property
    def texts(self) -> list[str]:
        return [line.text for line in self.lines]


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", _NORMALIZE.sub(" ", text.lower())).strip()


def match_section(text: str) -> str | None:
    """Canonical section for a heading-like text, or None."""
    key = _norm(text)
    if not key or len(key) > 45:
        return None
    if key in _ALIAS_TO_SECTION:
        return _ALIAS_TO_SECTION[key]
    hit = process.extractOne(key, list(_ALIAS_TO_SECTION), scorer=fuzz.ratio, score_cutoff=90)
    return _ALIAS_TO_SECTION[hit[0]] if hit else None


def _looks_like_heading(line: ExtractedLine, body_size: float) -> bool:
    text = line.text.strip()
    words = text.rstrip(":").split()
    if not words or len(words) > 5 or len(text) > 45:
        return False
    if re.search(r"[@\d|•]", text) or text.endswith((".", ",")):
        return False
    letters = [c for c in text if c.isalpha()]
    upper = bool(letters) and all(c.isupper() for c in letters)
    larger = body_size > 0 and line.size >= body_size * 1.12
    return line.heading_style or line.bold or upper or larger or text.endswith(":")


def split_sections(lines: list[ExtractedLine]) -> list[Section]:
    sizes = [ln.size for ln in lines if ln.size > 0]
    body_size = statistics.median(sizes) if sizes else 0.0
    sections = [Section("header", None)]
    for line in lines:
        text = line.text.strip()
        name = match_section(text)
        known_alias = name is not None and _norm(text) in _ALIAS_TO_SECTION
        # A known alias on its own line is a heading even without styling
        # ("Experience" in plain text); fuzzy matches need heading styling.
        if name and (
            known_alias and len(text.split()) <= 5 or _looks_like_heading(line, body_size)
        ):
            sections.append(Section(name, text.rstrip(":")))
        elif (
            _looks_like_heading(line, body_size)
            and line is not lines[0]
            and (line.heading_style or (line.bold and line.size >= body_size * 1.12))
            # The candidate's name is often styled as a title: keep it in the header.
            and not (sections[-1].name == "header" and looks_like_name(text))
        ):
            # Clearly styled heading we don't recognise: keep it as "other".
            sections.append(Section("other", text.rstrip(":")))
        else:
            sections[-1].lines.append(line)
    return [s for s in sections if s.lines or s.name != "header"]
