"""Entry extractors for resume sections (deterministic, no LLM)."""

import re
from dataclasses import dataclass, field

from app.parsing.contact import LOCATION_RE, REMOTE_RE, URL_RE
from app.parsing.dates import DateRange, find_date_range, find_year
from app.parsing.skills import dedupe_skills, find_skills, split_skill_list
from app.schemas.parsed_resume import (
    AwardEntry,
    CertificationEntry,
    EducationEntry,
    ExperienceEntry,
    ProjectEntry,
    PublicationEntry,
    SkillGroup,
)

BULLET_RE = re.compile(r"^\s*(?:[•●▪◦‣⁃∙·➢✓✔*>]|-(?=\s)|–(?=\s)|o(?=\s))\s*")
_SEGMENT_SPLIT = re.compile(r"\s*(?:\||•|·|\t| — | – | - |, (?=[A-Z])| @ )\s*")

TITLE_WORDS = {
    "engineer", "developer", "manager", "analyst", "intern", "internship", "director", "designer",
    "scientist", "consultant", "lead", "architect", "specialist", "coordinator", "associate",
    "assistant", "officer", "administrator", "head", "vp", "vice", "president", "founder",
    "co-founder", "owner", "researcher", "programmer", "technician", "representative",
    "executive", "strategist", "editor", "writer", "teacher", "professor", "instructor",
    "nurse", "accountant", "advisor", "principal", "staff", "senior", "junior", "sr", "jr",
    "fellow", "partner", "chief", "cto", "ceo", "cfo", "coo", "sre", "devops", "product",
    "recruiter", "marketer", "trainee", "apprentice", "contractor", "freelance", "freelancer",
    "volunteer", "tutor", "manager,", "agent", "clerk", "supervisor",
}  # fmt: skip
COMPANY_WORDS = {
    "inc", "inc.", "llc", "ltd", "ltd.", "corp", "corp.", "corporation", "company", "co.",
    "group", "technologies", "technology", "labs", "lab", "gmbh", "plc", "systems",
    "solutions", "software", "bank", "partners", "capital", "ventures", "studios", "studio",
    "agency", "consulting", "university", "college", "hospital", "institute", "foundation",
    "ag", "sa", "s.a.", "pvt", "limited", "holdings", "industries", "media", "networks",
}  # fmt: skip
INSTITUTION_RE = re.compile(
    r"\b(university|college|institute|school|academy|polytechnic|universit[ée]|conservatory|"
    r"iit|mit|ucla|nyu|bootcamp)\b",
    re.IGNORECASE,
)
DEGREE_RE = re.compile(
    r"\b(?P<deg>Ph\.?\s?D\.?|Doctor(?:ate)?(?: of [A-Z][a-z]+)?|M\.?B\.?A\.?|"
    r"Master(?:'s)?(?: of [A-Z][a-z]+(?: [A-Z][a-z]+)?)?|"
    r"Bachelor(?:'s)?(?: of [A-Z][a-z]+(?: [A-Z][a-z]+)?)?|"
    r"Associate(?:'s)?(?: of [A-Z][a-z]+)?|"
    r"B\.?\s?S\.?c?\.?|B\.?\s?A\.?|M\.?\s?S\.?c?\.?|M\.?\s?A\.?|"
    r"B\.?\s?Tech|M\.?\s?Tech|B\.?\s?Eng|M\.?\s?Eng|B\.?\s?E\.?|M\.?\s?E\.?|J\.?D\.?|M\.?D\.?|"
    r"High School Diploma|GED|Diploma|Certificate)"
    r"(?=[\s,.(]|$)"
    r"(?:\s*(?:in|of|,|-|–)?\s*(?P<field>[A-Z][A-Za-z&/ ]{2,60}?))?"
    r"(?=\s*(?:[,|(–-]|\d|$))"
)
GPA_RE = re.compile(r"\bGPA[:\s]*([0-4]\.\d{1,2})(?:\s*/\s*4(?:\.0+)?)?", re.IGNORECASE)


def is_bullet(text: str) -> bool:
    return bool(BULLET_RE.match(text))


def strip_bullet(text: str) -> str:
    return BULLET_RE.sub("", text, count=1).strip()


def _segments(text: str) -> list[str]:
    return [s.strip(" ,;:-–—") for s in _SEGMENT_SPLIT.split(text) if s.strip(" ,;:-")]


def _words(text: str) -> set[str]:
    return {w.lower().strip(",.()") for w in text.split()}


# Role nouns that usually END a job title, and suffixes that END company names.
ROLE_NOUNS = {
    "engineer", "developer", "manager", "analyst", "intern", "director", "designer",
    "scientist", "consultant", "architect", "specialist", "coordinator", "associate",
    "assistant", "officer", "administrator", "lead", "head", "researcher", "programmer",
    "technician", "representative", "executive", "strategist", "editor", "writer", "teacher",
    "professor", "instructor", "nurse", "accountant", "advisor", "founder", "co-founder",
    "president", "partner", "recruiter", "marketer", "trainee", "contractor", "supervisor",
    "owner", "fellow", "sre", "cto", "ceo", "cfo", "coo", "vp", "tutor",
}  # fmt: skip
LEGAL_SUFFIXES = {
    "inc", "inc.", "llc", "ltd", "ltd.", "corp", "corp.", "corporation", "co.", "gmbh", "plc",
    "ag", "sa", "s.a.", "pvt", "limited", "llp", "lp", "bv", "b.v.", "oy", "ab", "srl", "pty",
}  # fmt: skip


def _last_word(text: str) -> str:
    words = text.lower().strip(" ,.()").split()
    return words[-1].strip(",()") if words else ""


def _title_score(text: str) -> int:
    return len(_words(text) & TITLE_WORDS) + (2 if _last_word(text) in ROLE_NOUNS else 0)


def _company_score(text: str) -> int:
    return len(_words(text) & COMPANY_WORDS) + (2 if _last_word(text) in LEGAL_SUFFIXES else 0)


def _is_location(text: str) -> bool:
    return bool(LOCATION_RE.fullmatch(text.strip()) or REMOTE_RE.fullmatch(text.strip()))


@dataclass
class _Block:
    header: list[str] = field(default_factory=list)
    body: list[str] = field(default_factory=list)


def group_blocks(lines: list[str]) -> list[_Block]:
    """Group lines into entries: header line(s) followed by bullet/body lines.

    A new entry starts at a non-bullet line that follows body lines, or at a
    non-bullet line carrying a date range when the current header already has one.
    """
    blocks: list[_Block] = []
    for raw in lines:
        text = raw.strip()
        if not text:
            continue
        if is_bullet(text):
            if not blocks:
                blocks.append(_Block())
            blocks[-1].body.append(strip_bullet(text))
            continue
        cur = blocks[-1] if blocks else None
        has_date = find_date_range(text) is not None
        cur_has_date = cur is not None and any(find_date_range(h) for h in cur.header)
        continuation = (
            cur is not None and cur.body and text[:1].islower()  # wrapped bullet text
        )
        if continuation:
            cur.body[-1] = f"{cur.body[-1]} {text}"
        elif cur is None or cur.body or (has_date and cur_has_date) or len(cur.header) >= 4:
            blocks.append(_Block(header=[text]))
        else:
            cur.header.append(text)
    return blocks


def _without_dates(text: str) -> str:
    dr = find_date_range(text)
    if dr is None:
        return text.strip()
    return (text[: dr.span[0]] + " " + text[dr.span[1] :]).strip(" ,|-\u2013\u2014()")


def _pop_dates(header: list[str]) -> tuple[DateRange | None, list[str]]:
    rest, found = [], None
    for line in header:
        dr = None if found else find_date_range(line)
        if dr is not None and (dr.start or dr.is_current or dr.end):
            found = dr
            line = (line[: dr.span[0]] + " " + line[dr.span[1] :]).strip(" |,-–—()")
        if line.strip():
            rest.append(line.strip())
    return found, rest


# ------------------------------------------------------------- experience
def parse_experience(lines: list[str]) -> list[ExperienceEntry]:
    entries = []
    for block in group_blocks(lines):
        dates, header = _pop_dates(block.header)
        location = None
        for i, line in enumerate(header):  # "Initech LLC (Austin, TX)"
            for m in re.finditer(r"\(([^)]*)\)", line):
                if _is_location(m.group(1)):
                    location = location or m.group(1).strip()
                    header[i] = line.replace(m.group(0), " ").strip()
        parts: list[str] = []
        for line in header:
            if " at " in line and _title_score(line.split(" at ")[0]):
                left, _, right = line.partition(" at ")
                parts += [left, *_segments(right)]
            else:
                parts += _segments(line)
        location = location or next((p for p in parts if _is_location(p)), None)
        parts = [p for p in parts if p != location]

        title = company = None
        if parts:
            scored = sorted(parts, key=lambda p: _title_score(p) - _company_score(p), reverse=True)
            if _title_score(scored[0]) > _company_score(scored[0]):
                title = scored[0]
            rest = [p for p in parts if p != title]
            company_pick = max(rest, key=_company_score) if rest else None
            if company_pick and _company_score(company_pick):
                company = company_pick
            # Fall back to position: "Title, Company" is the most common order.
            remaining = [p for p in parts if p not in (title, company)]
            if title is None and remaining:
                title = remaining.pop(0)
            if company is None and remaining:
                company = remaining.pop(0)
        entry = ExperienceEntry(
            title=title,
            company=company,
            location=location,
            start_date=dates.start if dates else None,
            end_date=None if dates and dates.is_current else (dates.end if dates else None),
            is_current=bool(dates and dates.is_current),
            bullets=block.body,
            skills=find_skills(" ".join([*block.body, *header])),
        )
        if entry.title or entry.company or entry.bullets:
            entries.append(entry)
    return entries


# -------------------------------------------------------------- education
def parse_education(lines: list[str]) -> list[EducationEntry]:
    entries: list[EducationEntry] = []
    cur: EducationEntry | None = None

    def new() -> EducationEntry:
        nonlocal cur
        cur = EducationEntry()
        entries.append(cur)
        return cur

    for raw in lines:
        text = strip_bullet(raw) if is_bullet(raw) else raw.strip()
        if not text:
            continue
        inst = INSTITUTION_RE.search(text)
        deg = DEGREE_RE.search(text)
        if cur is None or (inst and cur.institution) or (deg and cur.degree and not inst):
            if inst or deg:
                new()
            elif cur is None:
                new()
        if cur is None:  # unreachable: new() always sets it
            continue
        dr = find_date_range(text)
        if dr:
            cur.start_date = cur.start_date or dr.start
            cur.end_date = cur.end_date or dr.end
        if m := GPA_RE.search(text):
            cur.gpa = cur.gpa or m.group(1)
        if inst and not cur.institution:
            # Split only on strong separators: commas are part of names
            # ("University of California, Berkeley").
            segs = [s for s in re.split(r"\s*(?:\||\t| \u2013 | \u2014 | - )\s*", text)
                    if INSTITUTION_RE.search(s)]  # fmt: skip
            inst_text = segs[0] if segs else text
            if deg_m := DEGREE_RE.search(inst_text):
                inst_text = inst_text.replace(deg_m.group(0), " ")
            inst_text = GPA_RE.sub(" ", inst_text)
            cur.institution = _without_dates(inst_text).strip(" ,;-") or None
        if deg and not cur.degree:
            cur.degree = deg.group("deg").strip()
            fld = (deg.group("field") or "").strip()
            if fld and not INSTITUTION_RE.search(fld) and fld.lower() not in {"gpa"}:
                cur.field_of_study = fld
        if not inst and not deg and not dr and not GPA_RE.search(text):
            if re.match(r"(?i)(honou?rs|cum laude|dean'?s list|magna|summa|award)", text) or (
                "honor" in text.lower()
            ):
                cur.honors.append(text)
    return [e for e in entries if e.institution or e.degree]


# ----------------------------------------------------------------- skills
_PROSE_WORDS = {
    "with", "and", "the", "of", "for", "using", "to", "experienced", "experience",
    "proficient", "familiar", "knowledge", "strong", "including", "such", "various", "modern",
}  # fmt: skip


def _is_prose(item: str) -> bool:
    words = item.lower().split()
    return len(words) > 5 or (len(words) >= 3 and bool(_PROSE_WORDS & set(words)))


def parse_skills(lines: list[str]) -> tuple[list[str], list[SkillGroup]]:
    skills: list[str] = []
    groups: list[SkillGroup] = []
    for raw in lines:
        text = strip_bullet(raw) if is_bullet(raw) else raw.strip()
        if not text:
            continue
        category, raw_items = split_skill_list(text)
        items: list[str] = []
        for item in raw_items:
            # Long fragments are prose ("Experienced with Kubernetes"): mine them.
            items += find_skills(item) if _is_prose(item) else [item]
        items = dedupe_skills(items)
        skills += items
        if category and items:
            groups.append(SkillGroup(name=category, skills=items))
    return dedupe_skills(skills), groups


# ------------------------------------------------------- simple list items
def _items(lines: list[str]) -> list[tuple[str, list[str]]]:
    """(item line, detail bullets) pairs for list-like sections."""
    out: list[tuple[str, list[str]]] = []
    for raw in lines:
        text = raw.strip()
        if not text:
            continue
        if is_bullet(text) and out and not out[-1][1] and len(lines) > 1 and _looks_detail(text):
            out[-1][1].append(strip_bullet(text))
        elif is_bullet(text):
            out.append((strip_bullet(text), []))
        elif out and text[:1].islower():
            prev, details = out[-1]
            out[-1] = (f"{prev} {text}", details)
        else:
            out.append((text, []))
    return out


def _looks_detail(text: str) -> bool:
    return len(strip_bullet(text).split()) > 8


_LIST_ITEM_SPLIT = re.compile(r"\s*(?:\||\u2022|\u00b7|\t| \u2014 | \u2013 |, (?=[A-Z]))\s*")


def _split_name_rest(text: str) -> tuple[str, list[str]]:
    """Split a list item into name and details. A plain " - " stays inside the
    name ("Solutions Architect - Associate"); commas, pipes and dashes split."""
    segs = [s.strip(" ,;:") for s in _LIST_ITEM_SPLIT.split(text) if s.strip(" ,;:")]
    return (segs[0] if segs else text), segs[1:]


def parse_certifications(lines: list[str]) -> list[CertificationEntry]:
    out = []
    for text, _ in _items(lines):
        year = find_year(text)
        cleaned = _without_dates(text)
        name, rest = _split_name_rest(cleaned)
        cred = next((r for r in rest if re.search(r"(?i)(credential|id)[:#]?\s*\w", r)), None)
        issuer = next((r for r in rest if r != cred), None)
        out.append(CertificationEntry(name=name, issuer=issuer, date=year, credential_id=cred))
    return out


def parse_projects(lines: list[str]) -> list[ProjectEntry]:
    out = []
    for block in group_blocks(lines):
        if not block.header:
            if out:
                out[-1].bullets += block.body
            continue
        head = " ".join(block.header)
        url_m = URL_RE.search(head)
        url = url_m.group(0) if url_m and "." in url_m.group(0) else None
        if url:
            head = head.replace(url, "").strip(" ()|,")
        head = _without_dates(head)
        m = re.match(r"^(?P<name>.+?)\s*(?:[:|\u2013\u2014]| - )\s*(?P<desc>.+)$", head)
        name, desc = (m["name"], m["desc"]) if m else (head, None)
        out.append(
            ProjectEntry(
                name=name.strip() or head,
                description=desc.strip() if desc else None,
                url=("https://" + url) if url and not url.startswith("http") else url,
                technologies=find_skills(" ".join([head, *block.body])),
                bullets=block.body,
            )
        )
    return out


def parse_publications(lines: list[str]) -> list[PublicationEntry]:
    out = []
    for text, _ in _items(lines):
        quoted = re.search(r"[\"“](.+?)[\"”]", text)
        title = quoted.group(1) if quoted else _split_name_rest(text)[0]
        rest = text.replace(quoted.group(0), "") if quoted else text.replace(title, "", 1)
        year = find_year(rest)
        url_m = URL_RE.search(rest)
        venue_text = rest
        if year:
            venue_text = re.sub(re.escape(year[:4]) + r"(-\d\d)?", "", venue_text)
        if url_m:
            venue_text = venue_text.replace(url_m.group(0), "")
        venue = venue_text.strip(" ,.|-()–") or None
        out.append(PublicationEntry(title=title.strip().rstrip(","), venue=venue, date=year,
                                    url=url_m.group(0) if url_m else None))  # fmt: skip
    return out


def parse_awards(lines: list[str]) -> list[AwardEntry]:
    out = []
    for text, details in _items(lines):
        year = find_year(text)
        cleaned = _without_dates(text)
        title, rest = _split_name_rest(cleaned)
        out.append(
            AwardEntry(
                title=title,
                issuer=rest[0] if rest else None,
                date=year,
                description=" ".join(details) or None,
            )
        )
    return out


def parse_languages(lines: list[str]) -> list[str]:
    langs: list[str] = []
    for raw in lines:
        _, items = split_skill_list(strip_bullet(raw))
        langs += items
    return list(dict.fromkeys(langs))
