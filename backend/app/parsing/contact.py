"""Contact details: name, email, phone, location and profile links."""

import re

import phonenumbers

from app.documents.sandbox import ExtractedLine
from app.schemas.parsed_resume import ContactInfo

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
URL_RE = re.compile(
    r"(?:https?://)?(?:www\.)?[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[a-z]{2,}(?:/[^\s|,;)]*)?",
    re.IGNORECASE,
)
LINKEDIN_RE = re.compile(r"linkedin\.com/(?:in|pub)/[A-Za-z0-9_%-]+", re.IGNORECASE)
GITHUB_RE = re.compile(r"github\.com/[A-Za-z0-9_-]+", re.IGNORECASE)

US_STATES = (
    "AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH "
    "NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC"
).split()
COUNTRIES = (
    "USA|United States|Canada|United Kingdom|UK|India|Germany|France|Spain|Italy|Netherlands|"
    "Ireland|Australia|Singapore|Japan|Brazil|Mexico|Sweden|Switzerland|Poland|Israel|China|"
    "Portugal|Denmark|Norway|Finland|Belgium|Austria|New Zealand|South Africa|UAE|Nigeria|Kenya"
)
LOCATION_RE = re.compile(
    rf"\b([A-Z][A-Za-z.'-]+(?:\s[A-Z][A-Za-z.'-]+){{0,3}}),\s*"
    rf"({'|'.join(US_STATES)}|{COUNTRIES})\b(?:\s+\d{{5}})?"
)
REMOTE_RE = re.compile(r"\bremote\b", re.IGNORECASE)
_NAME_TOKEN = re.compile(r"^[A-Z][a-zA-Z'À-ɏ-]*\.?$|^[A-Z]\.$")
_NAME_PARTICLES = {"de", "da", "del", "van", "von", "der", "la", "le", "bin", "al"}

_TLDS = set(
    "com org net io dev ai co me app xyz tech info us uk ca de in edu gov page site blog design "
    "tv fm so sh cc ly gg to eu fr es it nl se ch au nz jp cn br mx pl pt ie be at dk no fi "
    "biz pro codes engineer works online cloud digital studio portfolio art".split()
)


def _plausible_url(raw: str) -> bool:
    if raw.lower().startswith(("http://", "https://")):
        return True
    host = raw.split("/", 1)[0].lower()
    return host.rsplit(".", 1)[-1] in _TLDS


_NOT_PORTFOLIO = ("linkedin.com", "github.com", "mailto:", "gmail.com", "outlook.com")


def _normalize_url(url: str) -> str:
    url = url.strip().rstrip(".,;)")
    if not url.lower().startswith(("http://", "https://")):
        url = "https://" + url
    return url


def find_email(text: str) -> str | None:
    m = EMAIL_RE.search(text)
    return m.group(0).lower() if m else None


def find_phone(text: str, region: str = "US") -> str | None:
    for match in phonenumbers.PhoneNumberMatcher(
        text, region, leniency=phonenumbers.Leniency.VALID
    ):
        num = match.number
        fmt = (
            phonenumbers.PhoneNumberFormat.NATIONAL
            if phonenumbers.region_code_for_number(num) == region
            else phonenumbers.PhoneNumberFormat.INTERNATIONAL
        )
        return phonenumbers.format_number(num, fmt)
    return None


def find_location(lines: list[str]) -> str | None:
    for text in lines:
        if EMAIL_RE.search(text) and "|" not in text and "•" not in text:
            continue
        m = LOCATION_RE.search(text)
        if m:
            return f"{m.group(1)}, {m.group(2)}"
    for text in lines:
        if REMOTE_RE.search(text) and len(text) < 40:
            return "Remote"
    return None


def looks_like_name(text: str) -> bool:
    text = text.strip()
    if not text or len(text) > 60 or any(c.isdigit() for c in text) or "@" in text:
        return False
    tokens = text.replace(",", " ").split()
    if not 2 <= len(tokens) <= 5:
        return False
    for t in tokens:
        if t.lower() in _NAME_PARTICLES:
            continue
        if not _NAME_TOKEN.match(t) and not (t.isupper() and t.isalpha()):
            return False
    return True


def _title_case_name(text: str) -> str:
    if text.isupper():
        return " ".join(
            w.lower() if w.lower() in _NAME_PARTICLES else w.capitalize() for w in text.split()
        )
    return text


def find_name(header: list[ExtractedLine]) -> str | None:
    """The most prominent name-like line near the top (style beats position)."""
    best: tuple[float, str] | None = None
    sizes = [ln.size for ln in header if ln.size > 0]
    max_size = max(sizes) if sizes else 0.0
    for pos, line in enumerate(header[:8]):
        # "Jordan Rivera | jordan@x.com" -> first segment
        first = re.split(r"\s*[|•·]\s*", line.text)[0].strip()
        if not looks_like_name(first) or LOCATION_RE.search(first):
            continue
        score = 3.0 * line.heading_style + 2.0 * line.bold - 0.5 * pos
        if max_size and line.size >= max_size:
            score += 2.0
        if best is None or score > best[0]:
            best = (score, first)
    return _title_case_name(best[1]) if best else None


def extract_contact(header: list[ExtractedLine], all_text: str, links: list[str]) -> ContactInfo:
    """Contact details from the header block, falling back to the whole text."""
    header_lines = [ln.text for ln in header]
    header_text = "\n".join(header_lines)
    info = ContactInfo()
    info.name = find_name(header)

    info.email = find_email(header_text) or find_email(all_text)
    info.phone = find_phone(header_text) or find_phone(all_text[:3000])
    info.location = find_location(header_lines) or None

    without_emails = EMAIL_RE.sub(" ", header_text)
    candidates = [
        *links,
        *(m.group(0) for m in URL_RE.finditer(without_emails) if _plausible_url(m.group(0))),
    ]
    for raw in candidates:
        if EMAIL_RE.fullmatch(raw.strip()) or raw.lower().startswith("mailto:"):
            continue
        url = _normalize_url(raw)
        low = url.lower()
        if (m := LINKEDIN_RE.search(low)) and not info.linkedin:
            info.linkedin = "https://www." + m.group(0)
        elif (m := GITHUB_RE.search(low)) and not info.github:
            info.github = "https://" + m.group(0)
        elif not any(x in low for x in _NOT_PORTFOLIO) and "." in low.split("//", 1)[-1]:
            domain = low.split("//", 1)[-1].split("/")[0]
            if info.email and domain.removeprefix("www.") == info.email.split("@")[1]:
                continue  # the email's own domain is not a portfolio
            if not info.portfolio:
                info.portfolio = url
            elif url not in info.other_links and url != info.portfolio:
                info.other_links.append(url)
    return info
