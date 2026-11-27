"""Semantic field matching: which fact (if any) belongs in a form field.

Pure functions over `FormField` and `ApplicantFacts`. The rules are about
meaning, not markup: "Legal Name", "Full name ✱" and an input with
autocomplete="name" all mean the same thing.

What it will NOT do:
* invent an answer: a required question with no reliable fact becomes
  `needs_you` and is listed in the review screen;
* use a package answer still marked "needs review" (those are placeholders
  such as "Please answer this yourself");
* tick consent, privacy or certification boxes (the user does that);
* guess voluntary self-identification (gender, race, veteran, disability):
  it picks "decline to answer" when offered, otherwise leaves it blank.
"""

import re
from dataclasses import dataclass, field
from typing import Literal

from rapidfuzz import fuzz

from app.automation.fields import CHOICE_KINDS, TEXT_KINDS, FormField, normalize
from app.parsing.skills import find_skills

Source = Literal["profile", "resume", "settings", "package_answer", "package", "user", "rule"]


@dataclass(frozen=True)
class AnswerFact:
    key: str  # agent 9 question key: work_authorization, sponsorship, experience:Python ...
    question: str
    answer: str
    usable: bool  # False while the package still marks it "needs review"


@dataclass(frozen=True)
class ApplicantFacts:
    full_name: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None
    phone: str | None = None
    location: str | None = None
    country: str | None = None
    linkedin: str | None = None
    github: str | None = None
    website: str | None = None
    current_company: str | None = None
    current_title: str | None = None
    years_experience: int | None = None
    salary_target: int | None = None
    salary_currency: str = "USD"
    school: str | None = None
    degree: str | None = None
    discipline: str | None = None
    grad_year: str | None = None
    grad_month: str | None = None  # "August"
    answers: tuple[AnswerFact, ...] = ()
    has_resume_file: bool = False
    has_cover_letter_file: bool = False
    cover_letter_text: str | None = None

    def answer(self, key: str) -> AnswerFact | None:
        return next((a for a in self.answers if a.key == key and a.usable), None)


@dataclass
class Plan:
    """The decision for one field."""

    status: Literal["fill", "upload", "needs_you", "consent", "skipped"]
    value: str | bool | list[str] | None = None  # text, yes/no, or option labels
    source: Source | str = ""
    concept: str = ""  # first_name, resume, work_authorization, custom ...
    reason: str = ""
    sensitive: bool = False
    options_hint: list[str] = field(default_factory=list)  # preferred option texts, in order


# ------------------------------------------------------------------ concepts
# (concept, pattern over the normalized field text). Order matters: specific first.
CONCEPTS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (name, re.compile(pattern))
    for name, pattern in (
        ("preferred_name", r"\bpreferred (first )?name\b|\bnickname\b|\bname you go by\b"),
        ("pronunciation", r"\bpronounce\b|\bpronunciation\b"),
        ("pronouns", r"\bpronouns?\b"),
        ("first_name", r"\bfirst name\b|\bgiven name\b|\bforename\b"),
        ("last_name", r"\blast name\b|\bsurname\b|\bfamily name\b"),
        ("full_name", r"^(your |full |legal |candidate )?name$|\bfull name\b|\blegal name\b"),
        ("other_email", r"\b(alternative|alternate|secondary|other|backup|personal) email\b"),
        ("email", r"\bemail\b"),
        ("phone", r"\bphone\b|\bmobile\b|\btelephone\b|\bcell\b"),
        ("linkedin", r"linkedin"),
        ("github", r"\bgithub\b"),
        ("website", r"\bwebsite\b|\bportfolio\b|\bpersonal (site|url|page)\b|\bblog\b"),
        ("resume", r"\bresume\b|\bcv\b|\bcurriculum vitae\b"),
        ("cover_letter", r"\bcover letter\b|\bmotivation letter\b"),
        ("eeo", r"\bgender\b|\bsex\b|\brace\b|\bethnic|\bhispanic\b|\blatin[oax]\b|\bveteran\b|"
                r"\bdisabilit|\bsexual orientation\b|\btransgender\b|\blgbt|\bvoluntary self\b"),
        ("consent", r"\bi (agree|consent|acknowledge|certify|confirm|understand)\b|\bconsent\b|"
                    r"\bprivacy (policy|notice)\b|\bterms (of|and)\b|\backnowledg|\bcertify\b|"
                    r"\bsms\b|\btext messages?\b|\bwhatsapp\b"),
        ("work_authorization", r"\bauthori[sz]ed to work\b|\blegally (authori[sz]ed|eligible|"
                               r"permitted|able)\b|\bright to work\b|\beligible to work\b|"
                               r"\bwork authori[sz]ation\b"),
        ("sponsorship", r"\bsponsor|\bvisa\b|\bh ?1 ?b\b"),
        ("relocation", r"\brelocat"),
        ("salary", r"\bsalary\b|\bcompensation\b|\bpay (expectation|range|requirement)|"
                   r"\bdesired pay\b|\bexpected pay\b"),
        ("start_date", r"\bstart date\b|\bwhen (can|could) you start\b|\bnotice period\b|"
                       r"\bavailab(le|ility) to start\b|\bearliest\b"),
        ("years_experience", r"\bhow many years\b|\byears of (professional |relevant |work )?"
                             r"experience\b"),
        ("how_heard", r"\bhear(d)? about\b|\bhow did you (find|learn|discover)\b|"
                      r"\breferral source\b|\bwhere did you (find|see)\b"),
        ("referrer", r"\breferred by\b|\bwho referred\b|\breferr(al|er) name\b"),
        ("current_title", r"\bcurrent (job )?title\b|\bcurrent (role|position)\b"),
        ("current_company", r"\bcurrent (company|employer|organi[sz]ation)\b|\bemployer\b|"
                            r"^company( name)?$|^org$|^organi[sz]ation$"),
        ("country", r"^country\b|\bcountry of residence\b|\bcountry\b"),
        ("school", r"^(school|university|college|institution)( name)?$|"
                   r"\bwhich (university|college|school)\b|\bschool you (attend|attended)\b"),
        ("degree", r"^degree( type| level)?$|\bhighest (level of )?(degree|education)\b"),
        ("discipline", r"^discipline$|\bfield of study\b|^major$|\bwhat did you study\b"),
        ("grad_year", r"\bend date year\b|\bgraduation year\b|\byear of graduation\b"),
        ("grad_month", r"\bend date month\b|\bgraduation month\b"),
        ("location", r"\blocation\b|\bcity\b|\bwhere are you (currently )?(based|located)\b|"
                     r"\bcurrent address\b|\bwhere do you live\b|"
                     r"\bwhere (do you plan on|will you be|would you be) working from\b"),
        ("why_company", r"\bwhy (do you want|are you interested|would you like|.*\bjoin\b)|"
                        r"\bwhat (excites|interests|attracts) you\b|\binterest in\b"),
        ("gpa", r"\bgpa\b|\bgrade point\b"),
        ("additional_info", r"\badditional information\b|\banything else\b|"
                            r"\badditional comments\b"),
    )
)  # fmt: skip
AUTOCOMPLETE = {
    "given-name": "first_name", "family-name": "last_name", "name": "full_name",
    "email": "email", "tel": "phone", "tel-national": "phone", "url": "website",
    "organization": "current_company", "organization-title": "current_title",
    "country": "country", "country-name": "country", "address-level2": "location",
}  # fmt: skip
DECLINE = re.compile(
    r"decline|prefer not|rather not|don.?t wish|do not wish|not wish to|choose not|"
    r"not to (say|disclose|answer|self.?identify)|(do not|don.?t) want to (answer|say|disclose)",
    re.IGNORECASE,
)
HOW_HEARD_PREFERENCE = (
    r"company (website|site|careers)|careers? (page|site|website)|job board|"
    r"(the )?website|online|internet|other"
)
YES = re.compile(r"^\s*(yes|y|true)\b", re.IGNORECASE)
NO = re.compile(r"^\s*(no|n|false)\b", re.IGNORECASE)


def concept_of(f: FormField) -> str | None:
    if f.autocomplete and f.autocomplete in AUTOCOMPLETE and f.kind not in CHOICE_KINDS:
        return AUTOCOMPLETE[f.autocomplete]
    if f.kind == "email":
        return "email"
    if f.kind == "tel":
        return "phone"
    # Hints (placeholder, name, nearby text) only count when the label is empty:
    # nearby text can belong to a neighbouring widget.
    texts = [f.label] if normalize(f.label) else list(f.hints)
    for text in texts:
        norm = normalize(text)
        for name, pattern in CONCEPTS:
            if norm and pattern.search(norm):
                if name in SHORT_ANSWER and (_is_long_question(text) or _is_yes_no(text)):
                    return None  # "Are you subject to agreements with your employer?" is not
                return name  # asking for the employer's name
    return None


# Facts that answer "what is your X?", never a long yes/no question that mentions X.
SHORT_ANSWER = frozenset({
    "first_name", "last_name", "full_name", "email", "phone", "current_company",
    "current_title", "linkedin", "github", "website", "location", "country",
})  # fmt: skip
_YES_NO_START = re.compile(r"^(are|do|did|will|would|can|could|have|has|is|were)\b", re.IGNORECASE)


def _is_yes_no(text: str) -> bool:
    """The question (last sentence) asks for yes or no: "...Are you willing to relocate?"."""
    sentences = [x.strip() for x in re.split(r"(?<=[.?!])\s+", text.strip()) if x.strip()]
    return (
        bool(sentences) and sentences[-1].endswith("?") and bool(_YES_NO_START.match(sentences[-1]))
    )


def _is_long_question(text: str) -> bool:
    return (
        text.strip().endswith("?")
        and len(text.split()) > 8
        and not text.lower().startswith(("where", "what", "which", "in which"))
    )


# ------------------------------------------------------------------ options
def yes_no(answer: str | bool | None) -> bool | None:
    if isinstance(answer, bool) or answer is None:
        return answer
    if YES.match(answer):
        return True
    if NO.match(answer):
        return False
    return None


def choose_option(
    wanted: str | bool, options: list[str], *, preferred: list[str] | None = None
) -> int | None:
    """Index of the option that means `wanted`, or None when none clearly does."""
    norm = [normalize(o) for o in options]
    if isinstance(wanted, bool):
        pattern = YES if wanted else NO
        hits = [i for i, o in enumerate(options) if pattern.match(o)]
        return hits[0] if len(hits) >= 1 else None
    for pat in preferred or []:
        rx = re.compile(pat, re.IGNORECASE)
        hit = next((i for i, o in enumerate(options) if rx.search(o)), None)
        if hit is not None:
            return hit
    target = normalize(wanted)
    if not target:
        return None
    for i, o in enumerate(norm):
        if o == target:
            return i
    starts = [i for i, o in enumerate(norm) if o.startswith(target) or target.startswith(o) and o]
    if len(starts) == 1:
        return starts[0]
    scored = sorted(((fuzz.WRatio(target, o), i) for i, o in enumerate(norm) if o), reverse=True)
    if scored and scored[0][0] >= 88 and (len(scored) == 1 or scored[0][0] - scored[1][0] >= 5):
        return scored[0][1]
    return None


US_STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois",
    "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon",
    "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia",
    "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}  # fmt: skip
_DEGREES = (
    (r"\bph\.?\s?d\b|\bdoctor", "Doctor"),
    (r"\bmba\b|\bm\.?\s?(s|a|sc|eng)\.?(\s|$)|\bmaster", "Master"),
    (r"\bb\.?\s?(s|a|sc|eng|tech)\.?(\s|$)|\bbachelor", "Bachelor"),
    (r"\bassociate", "Associate"),
)


def degree_family(degree: str) -> str | None:
    """'B.S.' -> 'Bachelor', 'M.Sc' -> 'Master', 'PhD' -> 'Doctor'."""
    for pattern, family in _DEGREES:
        if re.search(pattern, degree, re.IGNORECASE):
            return family
    return None


def choose_location(wanted: str, options: list[str]) -> int | None:
    """'San Francisco, CA' is 'San Francisco, California, United States', not
    'San Francisco Cajonos, Oaxaca'."""
    parts = [p.strip() for p in wanted.split(",") if p.strip()]
    if not parts:
        return None
    city = normalize(parts[0])
    region = parts[1] if len(parts) > 1 else ""
    region_full = normalize(US_STATES.get(region.upper(), region))
    same_city = [i for i, o in enumerate(options) if normalize(o.split(",")[0]) == city]
    if len(same_city) == 1:
        return same_city[0]
    if region_full:
        hits = [i for i in same_city if region_full in normalize(options[i])]
        if len(hits) == 1:
            return hits[0]
    return None


_RANGE = re.compile(
    r"(\d+)\s*(?:-|to|\u2013)\s*(\d+)|(\d+)\s*\+|(?:less than|under|<)\s*(\d+)|"
    r"(?:more than|over|>)\s*(\d+)|^\s*(\d+)\s*(?:years?)?\s*$",
    re.IGNORECASE,
)


def choose_years(years: float, options: list[str]) -> int | None:
    """The range option ('3-5 years', '6+ years', 'Less than 1 year') holding `years`."""
    hits = []
    for i, option in enumerate(options):
        m = _RANGE.search(option)
        if not m:
            continue
        lo_hi, plus, under, over, exact = (m.group(1), m.group(2)), m.group(3), m.group(4), \
            m.group(5), m.group(6)  # fmt: skip
        if lo_hi[0] and int(lo_hi[0]) <= years <= int(lo_hi[1]) + 0.99:
            hits.append(i)
        elif plus and years >= int(plus):
            hits.append(i)
        elif under and years < int(under):
            hits.append(i)
        elif over and years > int(over):
            hits.append(i)
        elif exact and int(exact) == int(years):
            hits.append(i)
    return hits[0] if len(hits) == 1 else None


def pick_option(
    concept: str | None,
    value: str | bool | list[str],
    options: list[str],
    *,
    preferred: list[str] | None = None,
) -> int | None:
    """The option that means `value` for this kind of question."""
    if isinstance(value, list):
        return None
    if concept == "location" and isinstance(value, str):
        idx = choose_location(value, options)
        if idx is not None:
            return idx
    if concept == "years_experience" and isinstance(value, str) and value.isdigit():
        idx = choose_years(float(value), options)
        if idx is not None:
            return idx
    if concept == "degree" and isinstance(value, str):
        family = degree_family(value) or value
        hits = [i for i, o in enumerate(options) if family.lower() in o.lower()]
        if len(hits) == 1:
            return hits[0]
    if concept == "grad_month" and isinstance(value, str):
        hits = [i for i, o in enumerate(options) if normalize(o)[:3] == normalize(value)[:3]]
        if len(hits) == 1:
            return hits[0]
    return choose_option(value, options, preferred=preferred)


# ------------------------------------------------------------------ planning
def plan_form(fields: list[FormField], facts: ApplicantFacts) -> list[Plan]:
    """Plans for every field. Form-level rule: with no cover-letter upload on
    the form, the letter goes into a free-text "cover letter" or "additional
    information" box (Lever's "Add a cover letter or anything else")."""
    plans = [plan_field(f, facts) for f in fields]
    has_letter_upload = any(
        f.kind == "file" and p.concept == "cover_letter" for f, p in zip(fields, plans, strict=True)
    )
    if not has_letter_upload and facts.cover_letter_text:
        for f, p in zip(fields, plans, strict=True):
            if (
                f.kind == "textarea"
                and p.concept in ("additional_info", "cover_letter")
                and (p.status != "fill")
            ):
                p.status, p.value, p.source = "fill", facts.cover_letter_text, "package"
                p.concept, p.reason = "cover_letter", "Your cover letter (the form has no upload)."
                break
    return plans


def plan_field(f: FormField, facts: ApplicantFacts) -> Plan:
    concept = concept_of(f)
    if f.kind == "file":
        return _plan_file(f, concept, facts)
    if concept == "eeo":
        return _plan_eeo(f)
    if concept == "consent" or _consent_options(f):
        return Plan("consent", concept="consent",
                    reason="Consent and certification boxes are left for you to tick.")  # fmt: skip
    if f.kind == "checkbox":  # a lone checkbox that is not consent: never guess
        return _missing(f, concept or "custom", "Tick this yourself if it applies.")

    value, source = _fact_for(concept, f, facts)
    if value is None and concept in (None, "why_company", "additional_info", "custom"):
        value, source, concept = _package_answer(f, facts, concept)
    if value is None:
        return _missing(f, concept or "custom", _why_missing(concept))
    if f.kind in CHOICE_KINDS:
        return _plan_choice(f, concept or "custom", value, source)
    if f.kind == "checkbox_group":
        return _missing(f, concept or "custom", "Pick the options that apply yourself.")
    if isinstance(value, bool):
        value = "Yes" if value else "No"
    return Plan("fill", value, source, concept or "custom")


def _plan_file(f: FormField, concept: str | None, facts: ApplicantFacts) -> Plan:
    if concept == "cover_letter":
        if facts.has_cover_letter_file:
            return Plan("upload", "cover_letter", "package", "cover_letter")
        return _missing(f, "cover_letter", "The package has no cover letter file.")
    if concept == "resume" or concept is None and "resume" in f.key.lower():
        if facts.has_resume_file:
            return Plan("upload", "resume", "package", "resume")
        return _missing(f, "resume", "The package has no tailored resume file.")
    return _missing(f, concept or "file", "An unknown file upload: attach it yourself.")


def _plan_eeo(f: FormField) -> Plan:
    labels = [o.label for o in f.options]
    if f.kind in CHOICE_KINDS and labels:
        idx = next((i for i, o in enumerate(labels) if DECLINE.search(o)), None)
        if idx is not None:
            return Plan("fill", labels[idx], "rule", "eeo", sensitive=True,
                        reason="Voluntary self-identification: chose to decline.")  # fmt: skip
    if f.kind == "combobox":  # options appear only when opened: try the decline wording
        return Plan("fill", "Decline to self-identify", "rule", "eeo", sensitive=True,
                    options_hint=[DECLINE.pattern],
                    reason="Voluntary self-identification: chose to decline.")  # fmt: skip
    plan = _missing(f, "eeo", "Voluntary self-identification is never guessed; answer it yourself.")
    plan.sensitive = True
    return plan


_CONSENT_OPTION = re.compile(r"\b(i )?(consent|agree|acknowledge)\b", re.IGNORECASE)


def _consent_options(f: FormField) -> bool:
    """A question answered with "Yes, I consent" / "I agree" is a consent question."""
    return f.kind in CHOICE_KINDS and any(_CONSENT_OPTION.search(o.label) for o in f.options)


def _missing(f: FormField, concept: str, reason: str) -> Plan:
    return Plan("needs_you" if f.required else "skipped", concept=concept, reason=reason)


def _why_missing(concept: str | None) -> str:
    return {
        "work_authorization": "Set your work authorization in Settings, or answer it here.",
        "sponsorship": "Confirm your sponsorship needs in Settings, or answer it here.",
        "relocation": "Set whether you are willing to relocate in Settings, or answer it here.",
        "salary": "Set a salary target in Settings, or answer it here.",
        "start_date": "Your profile has no start date or notice period.",
        "why_company": "Write why you want to work here (it should be in your own words).",
        "pronouns": "Pronouns are never guessed.",
        "pronunciation": "Only you can answer this.",
        "referrer": "Only you know who referred you.",
        "gpa": "Your resume has no GPA.",
    }.get(concept or "", "No fact in your profile or package answers this question.")


def _fact_for(
    concept: str | None, f: FormField, facts: ApplicantFacts
) -> tuple[str | bool | None, str]:
    simple: dict[str, tuple[str | None, str]] = {
        "full_name": (facts.full_name, "resume"),
        "first_name": (facts.first_name, "resume"),
        "preferred_name": (facts.first_name, "resume"),
        "last_name": (facts.last_name, "resume"),
        "email": (facts.email, "resume"),
        "phone": (facts.phone, "resume"),
        "linkedin": (facts.linkedin, "resume"),
        "github": (facts.github, "resume"),
        "website": (facts.website, "resume"),
        "location": (facts.location, "resume"),
        "country": (facts.country, "profile"),
        "current_company": (facts.current_company, "resume"),
        "current_title": (facts.current_title, "resume"),
    }
    if concept in simple:
        return simple[concept]
    if concept == "years_experience":
        return _years(f, facts)
    if concept in ("work_authorization", "sponsorship", "relocation"):
        a = facts.answer(concept)
        if a is None:
            return None, ""
        if f.kind in CHOICE_KINDS or f.kind == "checkbox":
            decided = yes_no(a.answer)
            if decided is None and concept == "work_authorization":
                decided = _us_authorized(a.answer, f.label)
            return (decided, "package_answer") if decided is not None else (None, "")
        if f.kind == "textarea":
            return a.answer, "package_answer"
        decided = yes_no(a.answer)
        return ("Yes" if decided else "No", "package_answer") if decided is not None else (
            a.answer, "package_answer")  # fmt: skip
    if concept == "salary":
        a = facts.answer("salary_expectations")
        if f.kind == "number" and facts.salary_target is not None and a is not None:
            return str(facts.salary_target), "settings"
        if a is not None and f.kind == "textarea":
            return a.answer, "package_answer"
        if a is not None and facts.salary_target is not None:
            return f"{facts.salary_target:,} {facts.salary_currency}", "settings"
        return None, ""
    if concept == "how_heard":
        return "Company careers page", "rule"
    education = {
        "school": facts.school, "discipline": facts.discipline, "grad_year": facts.grad_year,
        "grad_month": facts.grad_month,
    }  # fmt: skip
    if concept in education:
        return education[concept], "resume"
    if concept == "degree" and facts.degree:
        if f.kind in CHOICE_KINDS:  # "B.S." is the "Bachelor's Degree" option
            return degree_family(facts.degree) or facts.degree, "resume"
        return facts.degree, "resume"
    if concept == "cover_letter" and f.kind in TEXT_KINDS and facts.cover_letter_text:
        return facts.cover_letter_text, "package"
    return None, ""


_MIN_YEARS = re.compile(
    r"(?:minimum of|at least|more than|over|min\.?)\s*(\d+)\s*\+?\s*years|(\d+)\s*\+\s*years",
    re.IGNORECASE,
)
_ABOUT_YEARS = re.compile(r"about (\d+(?:\.\d+)?) years", re.IGNORECASE)


def _years(f: FormField, facts: ApplicantFacts) -> tuple[str | bool | None, str]:
    """Total years for a general question; a skill's own reviewed years when the
    question names a technology ("5 years of experience building in AWS")."""
    skills = find_skills(f.label)
    years: float | None
    source = "profile"
    if skills:
        a = next((facts.answer(f"experience:{s}") for s in skills if facts.answer(
            f"experience:{s}")), None)  # fmt: skip
        m = _ABOUT_YEARS.search(a.answer) if a else None
        if m is None or len(skills) > 1:
            return None, ""
        years, source = float(m.group(1)), "package_answer"
    else:
        if facts.years_experience is None:
            return None, ""
        years = float(facts.years_experience)
    if f.kind in CHOICE_KINDS:
        need = _MIN_YEARS.search(f.label)
        if need is None:
            return str(int(years)), source  # a range menu: the option holding the number
        return years >= int(need.group(1) or need.group(2)), source
    return str(int(years)), source


_US_STATUS = re.compile(
    r"\b(u\.?s\.? citizen|us citizen|united states citizen|citizen of the united states|"
    r"permanent resident|green card|authori[sz]ed to work in the (u\.?s\.?|us|united states))\b",
    re.IGNORECASE,
)
_US_QUESTION = re.compile(r"\b(united states|u\.s\.|usa)\b|\bthe us\b|\bin us\b", re.IGNORECASE)


def _us_authorized(status: str, question: str) -> bool | None:
    """'US citizen' answers "authorized to work in the United States?" with
    Yes; a question about another (or an unnamed) country stays with the user."""
    if _US_STATUS.search(status) and _US_QUESTION.search(question):
        return True
    return None


def _package_answer(
    f: FormField, facts: ApplicantFacts, concept: str | None
) -> tuple[str | None, str, str | None]:
    """A free-text question answered by a reviewed package answer."""
    if f.kind not in TEXT_KINDS:
        return None, "", concept
    if concept == "why_company":
        a = facts.answer("why_company")
        return (a.answer, "package_answer", concept) if a else (None, "", concept)
    label = normalize(f.label)
    best: tuple[float, AnswerFact | None] = (0.0, None)
    for a in facts.answers:
        if not a.usable or a.key.startswith(("work_authorization", "sponsorship", "relocation")):
            continue
        score = fuzz.token_set_ratio(label, normalize(a.question))
        if score > best[0]:
            best = (score, a)
    if best[1] is not None and best[0] >= 90:
        return best[1].answer, "package_answer", f"answer:{best[1].key}"
    return None, "", concept


def _plan_choice(f: FormField, concept: str, value: str | bool | list[str], source: str) -> Plan:
    if isinstance(value, list):
        return Plan("fill", value, source, concept)
    labels = [o.label for o in f.options]
    preferred = [HOW_HEARD_PREFERENCE] if concept == "how_heard" else []
    if not labels:  # a combobox: options load when it opens; the filler chooses then
        return Plan("fill", value, source, concept, options_hint=preferred)
    idx = pick_option(concept, value, labels, preferred=preferred)
    if idx is None:
        wanted = "Yes" if value is True else "No" if value is False else str(value)
        return _missing(f, concept, f"None of the options matches “{wanted}”: choose one yourself.")
    return Plan("fill", labels[idx], source, concept)
