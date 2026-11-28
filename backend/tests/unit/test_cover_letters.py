"""Unit: Agent 8 cover letters, rule-based and Claude with checks."""

import dataclasses

from app.agents.agent_6_resume_tailoring import CandidateFacts, tailor
from app.agents.agent_8_cover_letters import (
    MAX_WORDS,
    MIN_WORDS,
    CoverLetterInput,
    _starts_with_verb,
    accept_claude,
    compose,
    evidence_items,
    evidence_sentences,
    split_title,
    word_count,
)
from app.agents.relevance import JobTerms
from app.agents.truthfulness import check_text, facts_from
from app.schemas.parsed_resume import CertificationEntry, ExperienceEntry, ParsedResume
from tests.fixtures.resumes import SAMPLE_CANDIDATE, SAMPLE_JOB, sample_resume


def letter_input(resume: ParsedResume | None = None, **kw) -> CoverLetterInput:
    tailored = tailor(resume or sample_resume(), SAMPLE_JOB, SAMPLE_CANDIDATE)
    base = {
        "resume": tailored.content,
        "job": SAMPLE_JOB,
        "candidate": SAMPLE_CANDIDATE,
        "matched_skills": tuple(tailored.matched_skills),
        "sender_name": "Jordan Rivera",
    }
    return CoverLetterInput(**(base | kw))


def test_word_count():
    assert word_count("I built 2M-request APIs; it's fine.") == 6


def test_rule_based_letter_is_specific_truthful_and_sized():
    inp = letter_input()
    letter = compose(inp)
    body = letter.body
    assert letter.greeting == "Dear Stripe hiring team,"
    assert letter.text.startswith("Dear Stripe hiring team,\n\n")
    assert body.startswith("I am applying for the Senior Backend Engineer role at Stripe.")
    # Years and the latest real title; no composite title the candidate never held.
    assert (
        "I have 10+ years of professional experience, currently as Senior Software Engineer "
        "at Acme Payments." in body
    )
    assert (
        "Your posting asks for Python, PostgreSQL and AWS; here is where I have used them." in body
    )
    # A requirement from the posting that the quoted experience answers.
    assert "Your posting looks for \u201cStrong Python and PostgreSQL\u201d" in body
    # No stock phrases.
    assert "strong match" not in body and "glad to bring" not in body
    # Resume bullets quoted, grouped by role, most relevant first.
    assert "As Senior Software Engineer at Acme Payments, I built billing APIs in Python" in body
    # This small sample resume has only so much relevant material: the letter is a
    # little short rather than padded with unrelated bullets, and says so.
    assert 120 <= letter.word_count <= MAX_WORDS
    if letter.word_count < MIN_WORDS:
        assert any("nothing was invented" in n for n in letter.notes)
    assert "Kubernetes" not in body  # missing skills are never claimed
    facts = facts_from(inp.resume, extra_skills=SAMPLE_CANDIDATE.skills)
    assert check_text(body, facts, allow_numbers=["10"]) == []
    assert letter.method == "rules" and letter.facts_used
    assert any("why you want to work at Stripe" in n for n in letter.notes)
    doc = letter.letter(inp)
    assert doc.recipient == "Hiring team, Stripe" and doc.paragraphs == letter.paragraphs


def test_sparse_resume_gives_a_short_letter_with_a_note_not_padding():
    sparse = ParsedResume(
        experience=[ExperienceEntry(title="Engineer", company="X", bullets=["Wrote Python"])]
    )
    letter = compose(letter_input(sparse, candidate=CandidateFacts(roles=("Engineer",))))
    assert letter.word_count < MIN_WORDS
    assert any("nothing was invented" in n for n in letter.notes)


def test_long_resume_is_trimmed_to_the_limit():
    bullets = [
        f"Built Python service number {i} with PostgreSQL and a long tail of detail "
        "about its design, rollout, monitoring and ownership"
        for i in range(12)
    ]
    resume = sample_resume(
        experience=[
            ExperienceEntry(title="Engineer", company="X", bullets=bullets, is_current=True)
        ]
    )
    assert compose(letter_input(resume)).word_count <= MAX_WORDS


def test_evidence_grouping_and_verb_detection():
    assert _starts_with_verb("Built APIs") and _starts_with_verb("Shipped it")
    assert _starts_with_verb("Designed things")
    assert not _starts_with_verb("Responsible for on-call")
    assert not _starts_with_verb("AWS migrations")
    resume = sample_resume()
    facts = facts_from(resume)
    terms = JobTerms.from_job("Python engineer", ("Python",), "", ["Python"])
    items = evidence_items(resume, terms, facts)
    # Python-related bullet first, then the Python project, then resume order.
    assert [e.label for e in items[:3]] == [
        "Senior Software Engineer at Acme Payments",
        "pgwatch",
        "Senior Software Engineer at Acme Payments",
    ]
    acme, project = evidence_sentences(items[:3])
    assert acme == (
        "As Senior Software Engineer at Acme Payments, I built billing APIs in Python and "
        "postgres serving 2M requests a day and mentored 4 engineers through onboarding."
    )
    assert project.startswith("I built pgwatch, using Python and PostgreSQL")
    three = [e for e in items if e.group == 0]
    (sentence,) = evidence_sentences(three)
    assert sentence.endswith(
        "; mentored 4 engineers through onboarding; and cut AWS costs by "
        "30% by right-sizing instances."
    )


def test_claude_letter_is_used_only_when_it_passes_every_check():
    inp = letter_input()
    base = compose(inp)
    good = [
        "I am applying for the Senior Backend Engineer role at Stripe. " + "word " * 40,
        "At Acme Payments I built billing APIs in Python and PostgreSQL serving 2M requests a "
        "day, and I cut AWS costs by 30%. " + "more " * 60,
        "I would welcome a conversation with Stripe. " + "end " * 30,
    ]
    used = accept_claude(inp, compose(inp), good, "claude-sonnet-5-5")
    assert used.method == "claude" and used.model == "claude-sonnet-5-5"
    assert used.greeting == base.greeting

    invented = [p.replace("cut AWS costs by 30%", "ran Kubernetes for 50 teams") for p in good]
    kept = accept_claude(inp, compose(inp), invented, "m")
    assert kept.method == "rules"
    assert "Kubernetes" in kept.notes[-1] and "50" in kept.notes[-1]
    short = accept_claude(inp, compose(inp), ["Hi Stripe."], "m")
    assert short.method == "rules" and "words" in short.notes[-1]
    nameless = [p.replace("Stripe", "your company") for p in good]
    assert accept_claude(inp, compose(inp), nameless, "m").method == "rules"


def test_letter_respects_the_matched_skills_given():
    inp = dataclasses.replace(letter_input(), matched_skills=("Python", "Kubernetes"))
    body = compose(inp).body
    assert "Your posting asks for Python; here is where I have used it." in body
    assert "Kubernetes" not in body


def test_skills_only_listed_are_not_claimed_as_used():
    """A skill in the skills list but in no bullet is not presented as used at work."""
    inp = dataclasses.replace(letter_input(), matched_skills=("Python", "Docker"))
    body = compose(inp).body
    assert "Your posting asks for Python; here is where" in body and "Docker" not in body


def test_team_names_relevant_certifications_and_relevant_padding_only():
    job = dataclasses.replace(SAMPLE_JOB, title="Senior Backend Engineer, Payments Platform")
    resume = sample_resume(
        certifications=[CertificationEntry(name="AWS Certified Developer", issuer="Amazon"),
                        CertificationEntry(name="First Aid", issuer="Red Cross")]
    )  # fmt: skip
    inp = letter_input(resume, job=job)
    letter = compose(inp)
    assert letter.body.startswith(
        "I am applying for the Senior Backend Engineer role on the Payments Platform team at "
        "Stripe."
    )
    assert "I also hold the AWS Certified Developer (Amazon) certification." in letter.body
    assert "First Aid" not in letter.body
    assert "dotfiles" not in letter.body  # unrelated projects are not used as padding


def test_split_title():
    assert split_title("Senior Software Engineer, Agentic Ads Experience") == (
        "Senior Software Engineer",
        "Agentic Ads Experience",
    )
    assert split_title("Backend Engineer (Payments)") == ("Backend Engineer", "Payments")
    assert split_title("Software Engineer - Remote, US") == ("Software Engineer", None)
    assert split_title("Data Engineer") == ("Data Engineer", None)


def test_employment_arrangement_is_not_part_of_the_title_in_the_opening():
    resume = sample_resume()
    first = resume.experience[0].model_copy(update={"title": "Senior Software Engineer (Contract)"})
    resume = resume.model_copy(update={"experience": [first, *resume.experience[1:]]})
    body = compose(letter_input(resume)).body
    assert "currently as Senior Software Engineer at Acme Payments." in body
    assert "(Contract)" not in body.split("\n")[0]


def test_shared_terms_are_shown_as_written_not_as_stems():
    terms = JobTerms.from_job(
        "Backend Engineer", ["Build services for the business"], "Scale services.", []
    )
    shared = terms.shared_terms("Built backend services that the business relies on")
    assert "services" in shared and "business" in shared
    assert "servic" not in shared and "busines" not in shared


def test_lines_after_the_skill_lead_show_those_skills():
    resume = sample_resume()
    roles = [r.model_copy(deep=True) for r in resume.experience]
    # The only Java line sits in the oldest role, below more "relevant" lines.
    roles[-1] = roles[-1].model_copy(
        update={"bullets": ["Wrote Java utilities for data migration", *roles[-1].bullets]}
    )
    resume = resume.model_copy(update={"experience": roles})
    job = dataclasses.replace(SAMPLE_JOB, requirements=("Java experience",))
    inp = letter_input(resume, job=job, matched_skills=("Java",))
    middle = compose(inp).paragraphs[1]
    lead, after = middle.split("here is where I have used it. ", 1)
    assert "Java" in lead and "Java" in after.split(". ")[0]


def test_a_skill_named_only_as_a_plan_is_not_presented_as_used():
    resume = sample_resume()
    roles = [r.model_copy(deep=True) for r in resume.experience]
    roles[0] = roles[0].model_copy(
        update={"bullets": [*roles[0].bullets, "Designed APIs for future GenAI integration"]}
    )
    resume = resume.model_copy(update={"experience": roles})
    inp = letter_input(resume, matched_skills=("Python", "Generative AI"))
    lead = compose(inp).paragraphs[1].split(";")[0]
    assert lead == "Your posting asks for Python"
