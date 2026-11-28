"""Agent 4: rule-based job filtering (deterministic, no I/O, no tokens).

`evaluate(job, prefs)` runs every rule and returns a `FilterDecision` with one
`RuleCheck` per rule, so the UI can show exactly why a job was kept or
dropped. A job passes when every rule passes.

Rules, in order:

* duplicate        the same posting is already stored from another board
* company          company name matches an excluded company
* keywords         title, requirements or description contain an excluded keyword
* location         job location matches a preferred location
* remote           workplace type is acceptable for the remote preference
* employment_type  employment type is one of the wanted types
* salary           the posted pay can reach the minimum salary
* sponsorship      the posting does not rule out visa sponsorship (only checked
                   when the user needs sponsorship)

Missing information never rejects a job: a posting without a location,
workplace type, employment type or salary passes that rule with a note, since
most postings leave something out and a false rejection is invisible to the
user while a false pass is merely one more job to skim.

`fingerprint(job, prefs)` hashes everything the rules read. The filtering
service stores it and skips jobs whose fingerprint has not changed.
"""

import re
import unicodedata
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from typing import Any

from app.utils.hashing import hash_json

RULES_VERSION = "1"

# remote preference -> acceptable workplace types (unknown always passes).
ACCEPTED_WORKPLACES: dict[str, frozenset[str]] = {
    "any": frozenset({"remote", "hybrid", "onsite"}),
    "remote_only": frozenset({"remote"}),
    "hybrid": frozenset({"hybrid", "remote"}),
    "onsite": frozenset({"onsite", "hybrid"}),
}

# Preferred-location spellings that should match each other. Keys and values
# are folded (lower case, no accents); every term in a group matches the others.
_LOCATION_GROUPS: tuple[tuple[str, ...], ...] = (
    ("united states", "usa", "us", "u.s.", "u.s.a.", "america"),
    ("united kingdom", "uk", "u.k.", "great britain", "britain", "england"),
    ("new york", "nyc", "new york city"),
    ("san francisco", "sf", "bay area", "san francisco bay area"),
    ("los angeles", "la"),
    ("washington dc", "washington d.c.", "dc", "d.c."),
    ("european union", "eu", "europe", "emea"),
    ("united arab emirates", "uae"),
)
_US_GROUP = _LOCATION_GROUPS[0]
US_STATES: dict[str, str] = {
    "AL": "alabama", "AK": "alaska", "AZ": "arizona", "AR": "arkansas", "CA": "california",
    "CO": "colorado", "CT": "connecticut", "DE": "delaware", "FL": "florida", "GA": "georgia",
    "HI": "hawaii", "ID": "idaho", "IL": "illinois", "IN": "indiana", "IA": "iowa",
    "KS": "kansas", "KY": "kentucky", "LA": "louisiana", "ME": "maine", "MD": "maryland",
    "MA": "massachusetts", "MI": "michigan", "MN": "minnesota", "MS": "mississippi",
    "MO": "missouri", "MT": "montana", "NE": "nebraska", "NV": "nevada", "NH": "new hampshire",
    "NJ": "new jersey", "NM": "new mexico", "NY": "new york", "NC": "north carolina",
    "ND": "north dakota", "OH": "ohio", "OK": "oklahoma", "OR": "oregon", "PA": "pennsylvania",
    "RI": "rhode island", "SC": "south carolina", "SD": "south dakota", "TN": "tennessee",
    "TX": "texas", "UT": "utah", "VT": "vermont", "VA": "virginia", "WA": "washington",
    "WV": "west virginia", "WI": "wisconsin", "WY": "wyoming", "DC": "district of columbia",
}  # fmt: skip
_STATE_BY_NAME = {name: code for code, name in US_STATES.items()}
# "Austin, TX" / "Remote (NY)": a two-letter code after a comma or bracket, in capitals.
_STATE_CODE = re.compile(r"[,(]\s*([A-Z]{2})(?![A-Za-z])")
# Locations that mean "anywhere" for a remote job.
_ANYWHERE = ("anywhere", "worldwide", "global", "earth", "distributed")
REMOTE_TOKEN = "remote"  # noqa: S105 - a location word, not a secret

# Phrases that rule out sponsorship. Matched on folded, whitespace-normalized text.
_NO_SPONSORSHIP = re.compile(
    r"|".join(
        (
            r"(?:not|unable to|cannot|can't|won't|will not|do not|does not|don't|doesn't|"
            r"no longer|are not able to|is not able to)\s+"
            r"(?:\w+\s+){0,3}?(?:sponsor|offer|provide|support)\w*\s+"
            r"(?:\w+\s+){0,4}?(?:visa|sponsorship|work permit|h-?1b)",
            r"(?:unable to|cannot|can't|won't|will not|do not|does not|don't|doesn't|"
            r"not able to)\s+sponsor\b",
            r"(?:visa\s+)?sponsorship\s+(?:is\s+)?(?:not|un)\s*(?:available|offered|provided|possible)",
            r"without\s+(?:the\s+)?(?:need\s+for\s+)?(?:current\s+or\s+future\s+|future\s+)?"
            r"(?:employer\s+|visa\s+|employment\s+)?sponsorship",
            r"\bno\s+(?:visa\s+|employment\s+)?sponsorship",
            r"must\s+be\s+(?:a\s+)?(?:u\.?s\.?|united states)\s+citizen",
            r"(?:u\.?s\.?|united states)\s+citizenship\s+(?:is\s+)?required",
            r"requires?\s+(?:u\.?s\.?|united states)\s+citizenship",
        )
    )
)
_OFFERS_SPONSORSHIP = re.compile(
    r"(?:visa\s+)?sponsorship\s+(?:is\s+)?(?:available|offered|provided)"
    r"|(?:we|will|can|able to)\s+(?:\w+\s+){0,2}?sponsor\s+(?:\w+\s+){0,2}?visas?"
)


@dataclass(frozen=True)
class FilterJob:
    """The job fields the rules read."""

    title: str
    company_name: str
    location: str | None = None
    remote_type: str = "unknown"
    employment_type: str | None = None
    salary_min: int | None = None
    salary_max: int | None = None
    salary_currency: str | None = None
    description: str = ""
    requirements: tuple[str, ...] = ()
    duplicate_of: str | None = None


@dataclass(frozen=True)
class FilterPreferences:
    """The user's settings the rules read."""

    preferred_locations: tuple[str, ...] = ()
    remote_preference: str = "any"
    job_types: tuple[str, ...] = ()
    salary_min: int | None = None
    salary_currency: str = "USD"
    requires_sponsorship: bool = False
    excluded_companies: tuple[str, ...] = ()
    excluded_keywords: tuple[str, ...] = ()


@dataclass(frozen=True)
class RuleCheck:
    rule: str
    passed: bool
    reason: str


@dataclass(frozen=True)
class FilterDecision:
    passed: bool
    checks: list[RuleCheck] = field(default_factory=list)

    @property
    def failures(self) -> list[RuleCheck]:
        return [c for c in self.checks if not c.passed]

    @property
    def reason(self) -> str | None:
        """One line for jobs.filter_reason (None when the job passed)."""
        return "; ".join(c.reason for c in self.failures) or None

    def as_json(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "version": RULES_VERSION,
            "checks": [asdict(c) for c in self.checks],
        }


# ------------------------------------------------------------------ helpers
def fold(text: str | None) -> str:
    """Lower case, accents removed, whitespace collapsed."""
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFKD", text)
    plain = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return " ".join(plain.casefold().split())


@lru_cache(maxsize=1024)
def _word_pattern(term: str) -> re.Pattern[str]:
    """Whole-word match for a folded term (punctuation inside the term is literal)."""
    return re.compile(rf"(?<![\w]){re.escape(term)}(?![\w])")


def contains_term(text: str, term: str) -> bool:
    """`term` appears in `text` as whole words (both folded)."""
    return bool(term) and _word_pattern(term).search(text) is not None


@lru_cache(maxsize=1)
def _location_aliases() -> dict[str, tuple[str, ...]]:
    out: dict[str, tuple[str, ...]] = {}
    for group in _LOCATION_GROUPS:
        for term in group:
            out[term] = group
    return out


def location_terms(preference: str) -> tuple[str, ...]:
    """A preferred location and the spellings that mean the same place."""
    term = fold(preference)
    return _location_aliases().get(term, (term,))


def us_states_in(location: str) -> set[str]:
    """US state codes named in a location string ('Austin, TX', 'Remote - Texas')."""
    found = {m for m in _STATE_CODE.findall(location) if m in US_STATES}
    folded = fold(location)
    # "washington" alone is ambiguous with the city; count the state only as "washington state".
    found |= {
        code
        for name, code in _STATE_BY_NAME.items()
        if code != "WA" and contains_term(folded, name)
    }
    if contains_term(folded, "washington state"):
        found.add("WA")
    return found


def matches_location(job_location: str, preference: str) -> bool:
    folded = fold(job_location)
    terms = location_terms(preference)
    if any(contains_term(folded, t) for t in terms):
        return True
    states = us_states_in(job_location)
    if not states:
        return False
    if terms == _US_GROUP:
        return True  # "United States" matches any US state
    pref = fold(preference)
    wanted = _STATE_BY_NAME.get(pref) or (pref.upper() if pref.upper() in US_STATES else None)
    return wanted in states


def is_generic_remote(location: str | None) -> bool:
    """'Remote', 'Anywhere', 'Remote - Worldwide': no region attached."""
    folded = fold(location)
    if not folded:
        return True
    words = re.sub(r"[^\w\s]", " ", folded).split()
    return all(w == REMOTE_TOKEN or w in _ANYWHERE for w in words)


def _salary_top(job: FilterJob) -> int | None:
    return job.salary_max if job.salary_max is not None else job.salary_min


def _money(value: int, currency: str) -> str:
    return f"{currency} {value:,}"


# -------------------------------------------------------------------- rules
def check_duplicate(job: FilterJob, _prefs: FilterPreferences) -> RuleCheck:
    if job.duplicate_of:
        return RuleCheck("duplicate", False, "Duplicate of a job already found on another board")
    return RuleCheck("duplicate", True, "Not a duplicate")


def check_company(job: FilterJob, prefs: FilterPreferences) -> RuleCheck:
    company = fold(job.company_name)
    for excluded in prefs.excluded_companies:
        if contains_term(company, fold(excluded)):
            return RuleCheck("company", False, f"Company '{job.company_name}' is excluded")
    return RuleCheck("company", True, "Company not excluded")


def check_keywords(job: FilterJob, prefs: FilterPreferences) -> RuleCheck:
    if not prefs.excluded_keywords:
        return RuleCheck("keywords", True, "No excluded keywords set")
    places = (
        ("title", fold(job.title)),
        ("requirements", fold(" ".join(job.requirements))),
        ("description", fold(job.description)),
    )
    for keyword in prefs.excluded_keywords:
        term = fold(keyword)
        for where, text in places:
            if contains_term(text, term):
                return RuleCheck("keywords", False, f"Excluded keyword '{keyword}' in the {where}")
    return RuleCheck("keywords", True, "No excluded keywords found")


def check_location(job: FilterJob, prefs: FilterPreferences) -> RuleCheck:
    wanted = [p for p in prefs.preferred_locations if p.strip()]
    if not wanted:
        return RuleCheck("location", True, "No location preference set")
    remote_ok = job.remote_type == "remote" and prefs.remote_preference != "onsite"
    if remote_ok and any(fold(p) == REMOTE_TOKEN for p in wanted):
        return RuleCheck("location", True, "Remote job and 'Remote' is a preferred location")
    if not job.location:
        if remote_ok:
            return RuleCheck("location", True, "Remote job with no location restriction")
        return RuleCheck("location", True, "Location not listed")
    for pref in wanted:
        if fold(pref) != REMOTE_TOKEN and matches_location(job.location, pref):
            return RuleCheck("location", True, f"Location matches '{pref}'")
    if remote_ok and is_generic_remote(job.location):
        return RuleCheck("location", True, "Remote job open to any location")
    return RuleCheck(
        "location", False, f"Location '{job.location}' is not in your preferred locations"
    )


def check_remote(job: FilterJob, prefs: FilterPreferences) -> RuleCheck:
    accepted = ACCEPTED_WORKPLACES.get(prefs.remote_preference, ACCEPTED_WORKPLACES["any"])
    if prefs.remote_preference == "any":
        return RuleCheck("remote", True, "Any workplace type accepted")
    if job.remote_type == "unknown":
        return RuleCheck("remote", True, "Workplace type not stated")
    if job.remote_type in accepted:
        return RuleCheck("remote", True, f"{job.remote_type.capitalize()} is acceptable")
    wanted = prefs.remote_preference.replace("_", " ")
    return RuleCheck(
        "remote", False, f"{job.remote_type.capitalize()} job, but you want {wanted} work"
    )


def check_employment_type(job: FilterJob, prefs: FilterPreferences) -> RuleCheck:
    if not prefs.job_types:
        return RuleCheck("employment_type", True, "No employment type preference set")
    if not job.employment_type:
        return RuleCheck("employment_type", True, "Employment type not stated")
    if job.employment_type in prefs.job_types:
        return RuleCheck("employment_type", True, f"{_label(job.employment_type)} is wanted")
    return RuleCheck(
        "employment_type", False, f"{_label(job.employment_type)} is not a wanted employment type"
    )


def check_salary(job: FilterJob, prefs: FilterPreferences) -> RuleCheck:
    if prefs.salary_min is None:
        return RuleCheck("salary", True, "No minimum salary set")
    top = _salary_top(job)
    if top is None:
        return RuleCheck("salary", True, "Salary not listed")
    currency = job.salary_currency or prefs.salary_currency
    if currency != prefs.salary_currency:
        return RuleCheck("salary", True, f"Salary in {currency}, not compared")
    if top >= prefs.salary_min:
        return RuleCheck("salary", True, f"Pays up to {_money(top, currency)}")
    return RuleCheck(
        "salary",
        False,
        f"Pays up to {_money(top, currency)}, below your minimum of "
        f"{_money(prefs.salary_min, prefs.salary_currency)}",
    )


def check_sponsorship(job: FilterJob, prefs: FilterPreferences) -> RuleCheck:
    if not prefs.requires_sponsorship:
        return RuleCheck("sponsorship", True, "Sponsorship not needed")
    text = fold(" ".join((job.title, " ".join(job.requirements), job.description)))
    if (m := _NO_SPONSORSHIP.search(text)) is not None:
        return RuleCheck("sponsorship", False, f"Posting rules out sponsorship: '{m.group(0)}'")
    if _OFFERS_SPONSORSHIP.search(text):
        return RuleCheck("sponsorship", True, "Posting offers visa sponsorship")
    return RuleCheck("sponsorship", True, "Posting does not rule out sponsorship")


RULES = (
    check_duplicate,
    check_company,
    check_keywords,
    check_location,
    check_remote,
    check_employment_type,
    check_salary,
    check_sponsorship,
)


def evaluate(job: FilterJob, prefs: FilterPreferences) -> FilterDecision:
    checks = [rule(job, prefs) for rule in RULES]
    return FilterDecision(passed=all(c.passed for c in checks), checks=checks)


def fingerprint(job: FilterJob, prefs: FilterPreferences) -> str:
    """Hash of the rule version and every input the rules read."""
    return hash_json({"version": RULES_VERSION, "job": asdict(job), "prefs": asdict(prefs)})


def _label(employment_type: str) -> str:
    return employment_type.replace("_", "-").capitalize()
