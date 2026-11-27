"""How relevant a piece of resume text is to one job posting (pure, no I/O).

Skills from the taxonomy are strong signals but sparse: many postings name only
a few known skills, so ranking by skills alone ties, and every job would get
the same "most relevant" bullets. `JobTerms` adds the posting's own vocabulary
(content words from the title, requirements and description, weighted by where
they appear and how often) so evidence differs per job.

Used by Agent 6 (bullet and project order), Agent 8 (which experience a cover
letter quotes, which requirement it answers) and Agent 9 (why qualified).
"""

import re
from dataclasses import dataclass

from app.agents.truthfulness import Facts, skills_in
from app.parsing.skills import AMBIGUOUS, skill_aliases

SKILL_WEIGHT = 3.0
MAX_TERMS = 40
_WORD = re.compile(r"[a-z][a-z+#.-]{2,}")
STOPWORDS = frozenset(
    """
    about above across after again against all also among and any are around based been
    before being below between both but can could did does doing down during each either
    etc every few for from further had has have having her here hers him his how into its
    itself just least less like made make many may more most much must near need needs new
    not now off once only other our ours out over own per plus rather same she should since
    some such than that the their them then there these they this those through thus too
    under until upon very via was way well were what when where which while who whom whose
    why will with within without would you your yours able across work works working team
    teams role roles join joining company help helps including include includes strong
    experience experienced years year ability skills skill knowledge understanding using use
    used looking candidate candidates ideal great good excellent preferred required
    requirement requirements responsibilities responsible opportunity opportunities
    environment etc. well-being benefits salary equal employer applicants application apply
    background status status. please position positions people world mission culture
    """.split()
)


def _words(text: str) -> list[str]:
    return [w.strip(".-") for w in _WORD.findall(text.lower()) if w.strip(".-") not in STOPWORDS]


def stem(word: str) -> str:
    """Crude stemming so 'pipelines'/'pipeline' and 'deployed'/'deploy' meet."""
    for suffix in ("ations", "ation", "ings", "ing", "ies", "ers", "ed", "es", "s"):
        if len(word) > len(suffix) + 3 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


@dataclass(frozen=True)
class JobTerms:
    skills: frozenset[str]  # casefolded canonical skills the job asks for (that matter)
    terms: dict[str, float]  # stemmed content word -> weight

    @classmethod
    def from_job(
        cls, title: str, requirements: tuple[str, ...], description: str, skills: list[str]
    ) -> JobTerms:
        weights: dict[str, float] = {}
        for text, w in ((title, 3.0), (" ".join(requirements), 2.0), (description, 1.0)):
            for word in _words(text):
                weights[stem(word)] = weights.get(stem(word), 0.0) + w
        top = dict(sorted(weights.items(), key=lambda kv: -kv[1])[:MAX_TERMS])
        return cls(frozenset(s.casefold() for s in skills), top)

    def score(self, text: str, facts: Facts) -> float:
        """Skills the job wants (strong) + the job's own words (weak), in `text`."""
        found_skills = len(skills_in(text, facts) & self.skills)
        stems = {stem(w) for w in _words(text)}
        overlap = sum(self.terms.get(s, 0.0) for s in stems)
        return SKILL_WEIGHT * found_skills + overlap / 10.0

    def shared_terms(self, text: str) -> list[str]:
        """The job's terms found in `text`, as written in `text` ('services',
        not the stem 'servic'), most important first."""
        words: dict[str, str] = {}
        for w in _words(text):
            words.setdefault(stem(w), w)
        return [words[t] for t in self.terms if t in words]


def skill_matches(text: str, skill: str) -> list[re.Match[str]]:
    """Where `skill` (any known spelling: "postgres" for PostgreSQL, "GenAI" for
    Generative AI) is named in `text`. Ambiguous short names need matching case."""
    found: list[re.Match[str]] = []
    for name in skill_aliases(skill):
        ambiguous = name.lower() in AMBIGUOUS or len(name) <= 2
        if ambiguous and name.islower():
            continue  # "go", "rag": only the capitalised spelling is the skill
        flags = 0 if ambiguous else re.IGNORECASE
        pattern = rf"(?<![\w+#.]){re.escape(name)}(?![\w+#]|\.\w)"
        for m in re.finditer(pattern, text, flags):
            if not any(m.start() < f.end() and f.start() < m.end() for f in found):
                found.append(m)
    return found


def mentions(text: str, skill: str) -> bool:
    return bool(skill_matches(text, skill))


# A skill named after these words (or as "X-ready") is an intention or exposure,
# not use: "for future GenAI integration", "AI-ready platforms", "RAG concepts".
_WEAK_BEFORE = re.compile(
    r"(?i)\b(?:future|planned|upcoming|exposure to|familiar(?:ity)? with|learning|towards?|"
    r"interest in|aware(?:ness)? of)\b(?:\W+\w+){0,4}\W*$"
)
_WEAK_AFTER = re.compile(r"(?i)^[-\s]*(?:ready|oriented|concepts?|curious)\b")


def strong_mentions(line: str, skill: str) -> int:
    """Mentions of `skill` in `line` that describe use, not intent or exposure."""
    count = 0
    for m in skill_matches(line, skill):
        before, after = line[: m.start()], line[m.end() :]
        if not (_WEAK_BEFORE.search(before) or _WEAK_AFTER.match(after)):
            count += 1
    return count
