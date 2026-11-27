"""Shared, source-agnostic normalization helpers used by every connector.

Connector-specific mapping lives in each connector; these helpers only turn
common shapes (HTML, salary strings, workplace labels, dates) into the
normalized job fields.
"""

import html
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from html.parser import HTMLParser

from app.schemas.job import EmploymentType, RemoteType

MAX_DESCRIPTION_CHARS = 100_000
MAX_REQUIREMENTS = 40
MAX_REQUIREMENT_CHARS = 500

# ------------------------------------------------------------------ HTML
_BLOCK = {"p", "div", "section", "article", "ul", "ol", "table", "tr", "blockquote",
          "h1", "h2", "h3", "h4", "h5", "h6", "header", "footer"}  # fmt: skip
_HEADING = {"h1", "h2", "h3", "h4", "h5", "h6"}
_SKIP = {"script", "style", "noscript", "template", "svg"}


@dataclass
class _Block:
    kind: str  # "heading" | "item" | "text"
    text: str


class _Parser(HTMLParser):
    """Collects text blocks: headings, list items and paragraphs."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[_Block] = []
        self._buf: list[str] = []
        self._kind = "text"
        self._skip = 0
        self._li_depth = 0  # inside <li>: nested <p>/<div> belong to the item
        self._strong_only = True  # paragraph consisting only of bold text = heading

    def _flush(self) -> None:
        text = re.sub(r"[ \t\r\f\v]+", " ", "".join(self._buf)).strip()
        if text:
            kind = self._kind
            if kind == "text" and self._strong_only and len(text) <= 80 and not text.endswith("."):
                kind = "bold"
            self.blocks.append(_Block(kind, text))
        self._buf = []
        self._kind = "text"
        self._strong_only = True

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP:
            self._skip += 1
        elif tag == "br":
            self._buf.append("\n")
        elif tag == "li":
            self._flush()
            self._li_depth += 1
            self._kind = "item"
        elif self._li_depth and tag in _BLOCK and tag not in {"ul", "ol"}:
            self._buf.append(" ")  # <li><p>text</p></li>: same item
        elif tag in _HEADING:
            self._flush()
            self._kind = "heading"
        elif tag in _BLOCK:
            self._flush()

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP:
            self._skip = max(0, self._skip - 1)
        elif tag == "li":
            self._kind = "item"
            self._flush()
            self._li_depth = max(0, self._li_depth - 1)
            if self._li_depth:
                self._kind = "item"
        elif self._li_depth and tag in _BLOCK and tag not in {"ul", "ol"}:
            return
        elif tag in _HEADING or tag in _BLOCK:
            self._flush()

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        if data.strip() and self.lasttag not in {"strong", "b"}:
            self._strong_only = False
        self._buf.append(data)

    def close(self) -> None:
        super().close()
        self._flush()


def _blocks(markup: str) -> list[_Block]:
    parser = _Parser()
    parser.feed(markup)
    parser.close()
    return parser.blocks


def html_to_text(markup: str | None, *, escaped: bool = False) -> str:
    """Readable plain text: paragraphs separated by blank lines, list items as bullets."""
    if not markup:
        return ""
    if escaped:  # Greenhouse sends entity-escaped HTML
        markup = html.unescape(markup)
    lines = []
    for b in _blocks(markup):
        lines.append(f"• {b.text}" if b.kind == "item" else b.text)
    text = "\n\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text[:MAX_DESCRIPTION_CHARS]


# ---------------------------------------------------------- requirements
_REQUIREMENT_HEADINGS = re.compile(
    r"requir|qualif|what we value|what you('|’)?(ll)?\s+(need|bring|have)|who you are"
    r"|you (have|bring|might be|will need)|what we('|’)?re looking for|about you"
    r"|skills|experience|must.have|you should have|ideal candidate|preferred|nice.to.have"
    r"|bonus points|what it takes|are you a fit",
    re.IGNORECASE,
)


def _clip(item: str) -> str:
    item = item.strip(" •-*·")
    return item if len(item) <= MAX_REQUIREMENT_CHARS else item[: MAX_REQUIREMENT_CHARS - 1] + "…"


def extract_requirements(markup: str | None, *, escaped: bool = False) -> list[str]:
    """List items under requirement-like headings ("Qualifications", "Who you are", ...)."""
    if not markup:
        return []
    if escaped:
        markup = html.unescape(markup)
    out: list[str] = []
    in_section = False
    for b in _blocks(markup):
        if b.kind in {"heading", "bold"}:
            in_section = bool(_REQUIREMENT_HEADINGS.search(b.text))
        elif b.kind == "item" and in_section:
            out.append(_clip(b.text))
        if len(out) >= MAX_REQUIREMENTS:
            break
    return list(dict.fromkeys(i for i in out if i))


def requirements_from_sections(sections: list[tuple[str, str]]) -> list[str]:
    """(heading, html) pairs, as Lever provides them."""
    out: list[str] = []
    for heading, body in sections:
        if _REQUIREMENT_HEADINGS.search(heading):
            out += [_clip(b.text) for b in _blocks(body) if b.kind == "item"]
    return list(dict.fromkeys(i for i in out if i))[:MAX_REQUIREMENTS]


# ------------------------------------------------------- workplace / type
def infer_remote_type(
    workplace: str | None = None, location: str | None = None, *, is_remote: bool | None = None
) -> RemoteType:
    w = (workplace or "").lower().replace("-", "").replace("_", "").replace(" ", "")
    if w in {"remote"}:
        return "remote"
    if w in {"hybrid"}:
        return "hybrid"
    if w in {"onsite", "inoffice", "office"}:
        return "onsite"
    loc = (location or "").lower()
    if "hybrid" in loc:
        return "hybrid"
    if is_remote or re.search(r"\bremote\b|\banywhere\b|work from home|\bwfh\b", loc):
        return "remote"
    return "unknown"


_EMPLOYMENT = [
    (r"intern|apprentice|co-?op\b", "internship"),
    (r"part[\s-]?time", "part_time"),
    (r"contract|contractor|freelance|consultant", "contract"),
    (r"temp|short[\s-]?term|fixed[\s-]?term|seasonal", "temporary"),
    (r"full[\s-]?time|permanent|regular|salaried|fulltime", "full_time"),
]


def normalize_employment_type(raw: str | None, title: str | None = None) -> EmploymentType | None:
    text = (raw or "").lower()
    for pattern, value in _EMPLOYMENT:
        if text and re.search(pattern, text):
            return value  # type: ignore[return-value]
    if title and re.search(r"\bintern(ship)?\b", title, re.IGNORECASE):
        return "internship"
    return None


# ----------------------------------------------------------- compensation
@dataclass
class Salary:
    min: int | None = None
    max: int | None = None
    currency: str | None = None
    text: str | None = None
    extras: list[str] = field(default_factory=list)


_SYMBOLS = {"$": "USD", "€": "EUR", "£": "GBP", "C$": "CAD", "CA$": "CAD", "A$": "AUD"}
_AMOUNT = (
    r"(?P<{n}sym>CA\$|C\$|A\$|\$|\u20ac|\u00a3)?\s?"
    r"(?P<{n}num>\d{{1,3}}(?:[,.\s]\d{{3}})*(?:\.\d+)?|\d+(?:\.\d+)?)\s?(?P<{n}k>[kK])?"
)
_RANGE = re.compile(
    r"(?P<code>USD|EUR|GBP|CAD|AUD)?\s?"
    + _AMOUNT.format(n="a")
    + r"\s?(?:-|–|—|to)\s?(?P<code2>USD|EUR|GBP|CAD|AUD)?\s?"
    + _AMOUNT.format(n="b")
)
_SALARY_CONTEXT = re.compile(r"salary|base|pay|compensation|range|ote|earnings", re.IGNORECASE)
_HOURLY = re.compile(r"per hour|/\s?h(ou)?r|hourly", re.IGNORECASE)


def _amount(num: str, k: str | None) -> float:
    digits = re.sub(r"[,\s]", "", num)
    if re.fullmatch(r"\d{1,3}(\.\d{3})+", digits):  # European thousands: 120.000
        digits = digits.replace(".", "")
    value = float(digits)
    return value * 1000 if k else value


def parse_salary_text(text: str | None) -> Salary:
    """Annual salary range in free text, e.g. "$87,069-$124,385" or "€50K – €65K".

    Only ranges near a salary word and in a plausible annual band are used;
    hourly rates are left in the text but not turned into numbers.
    """
    if not text:
        return Salary()
    for m in _RANGE.finditer(text):
        window = text[max(0, m.start() - 120) : m.end() + 40]
        if not _SALARY_CONTEXT.search(window) or _HOURLY.search(window):
            continue
        sym = m.group("asym") or m.group("bsym")
        code = m.group("code") or m.group("code2") or (_SYMBOLS.get(sym) if sym else None)
        if not code:
            continue
        lo = _amount(m.group("anum"), m.group("ak") or m.group("bk"))
        hi = _amount(m.group("bnum"), m.group("bk"))
        if not (10_000 <= lo <= hi <= 5_000_000):
            continue
        sentence = re.split(r"(?<=[.!?])\s", window.strip())
        snippet = next((s for s in sentence if m.group(0) in s), m.group(0))
        return Salary(int(lo), int(hi), code, snippet.strip()[:300])
    return Salary()


def clean_salary(lo: float | None, hi: float | None) -> tuple[int | None, int | None]:
    """Whole units, swapped if reversed, rejected if implausible for a year."""
    lo_i = int(lo) if lo is not None and lo > 0 else None
    hi_i = int(hi) if hi is not None and hi > 0 else None
    if lo_i is not None and hi_i is not None and lo_i > hi_i:
        lo_i, hi_i = hi_i, lo_i
    for v in (lo_i, hi_i):
        if v is not None and not 1_000 <= v <= 10_000_000:
            return None, None
    return lo_i, hi_i


def format_money(value: int | None, currency: str | None) -> str:
    if value is None:
        return ""
    return f"{currency + ' ' if currency else ''}{value:,}"


# ------------------------------------------------------------------ dates
def parse_datetime(value: str | int | float | None) -> datetime | None:
    """ISO 8601 strings or epoch milliseconds -> aware UTC datetime."""
    if value is None or value == "":
        return None
    try:
        if isinstance(value, int | float):
            return datetime.fromtimestamp(value / 1000, UTC)
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError, OverflowError, OSError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def clean_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = re.sub(r"\s+", " ", value).strip()
    return text or None


def join_locations(*values: str | None, limit: int = 5) -> str | None:
    seen: dict[str, None] = {}
    for v in values:
        t = clean_text(v)
        if t:
            seen.setdefault(t, None)
    items = list(seen)
    if not items:
        return None
    text = "; ".join(items[:limit])
    return text + (f" (+{len(items) - limit} more)" if len(items) > limit else "")
