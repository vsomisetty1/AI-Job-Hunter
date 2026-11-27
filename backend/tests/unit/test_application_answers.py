"""Unit: Agent 9 application answers: built from facts, flagged when unsure."""

from datetime import date
from decimal import Decimal

from app.agents.agent_6_resume_tailoring import CandidateFacts, tailor
from app.agents.agent_9_application_answers import (
    AnswerJob,
    AnswerSettings,
    apply_polish,
    generate_answers,
    relocation,
    roles_using,
    salary_expectations,
    skill_experience,
    sponsorship,
    work_authorization,
    years_experience,
)
from tests.fixtures.resumes import SAMPLE_CANDIDATE, SAMPLE_JOB, sample_resume

TODAY = date(2026, 11, 27)
JOB = AnswerJob(SAMPLE_JOB, "San Francisco, CA", "hybrid", 180_000, 240_000, "USD")


def answers(settings: AnswerSettings | None = None, **kw):
    t = tailor(sample_resume(), SAMPLE_JOB, SAMPLE_CANDIDATE)
    return {
        a.key: a
        for a in generate_answers(
            t.content,
            SAMPLE_CANDIDATE,
            kw.pop("job", JOB),
            settings or AnswerSettings(),
            t.matched_skills,
            t.missing_skills,
            today=TODAY,
            **kw,
        )
    }


def test_answer_set_covers_the_common_questions():
    keys = list(answers())
    assert keys[:7] == [
        "why_company",
        "why_qualified",
        "salary_expectations",
        "relocation",
        "sponsorship",
        "work_authorization",
        "years_experience",
    ]
    assert keys[7:] == [
        "experience:Python",
        "experience:PostgreSQL",
        "experience:AWS",
        "experience:Kubernetes",
    ]


def test_every_answer_has_evidence_or_a_review_flag():
    for a in answers().values():
        assert a.answer.strip()
        assert a.evidence or a.needs_review, a.key
        assert 0 <= a.confidence <= 1
    row = answers()["why_qualified"].as_row()
    assert row["question_key"] == "why_qualified" and isinstance(row["confidence"], Decimal)


def test_why_qualified_quotes_the_most_relevant_resume_lines():
    a = answers()["why_qualified"].answer
    # Years and the latest real title; no composite title.
    assert a.startswith(
        "I have 10+ years of professional experience, currently as Senior Software Engineer "
        "at Acme Payments."
    )
    assert "As Senior Software Engineer at Acme Payments: Built billing APIs in Python" in a
    assert "Mentored" not in a  # unrelated to the posting


def test_why_company_draft_is_factual_and_flagged():
    a = answers()["why_company"]
    assert a.answer == (
        "I am interested in the Senior Backend Engineer role at Stripe. It centres on Python, "
        "PostgreSQL and AWS, which is the work my experience is built on."
    )
    assert a.needs_review


class TestSalary:
    def test_target_and_minimum_within_the_posted_range(self):
        a = salary_expectations(JOB, AnswerSettings(salary_target=200_000, salary_min=170_000))
        assert a.answer == (
            "My target base salary is USD 200,000 per year, and I would consider offers from "
            "USD 170,000, which is within the range in your posting, depending on the full "
            "compensation package."
        )
        assert not a.needs_review and a.source == "settings"

    def test_minimum_only_and_outside_the_range(self):
        a = salary_expectations(JOB, AnswerSettings(salary_min=300_000))
        assert a.answer.startswith("I am looking for a base salary of at least USD 300,000")
        assert "within the range" not in a.answer

    def test_nothing_set_is_flagged(self):
        a = salary_expectations(JOB, AnswerSettings())
        assert a.needs_review and a.confidence < 0.5 and "USD" not in a.answer


class TestRelocation:
    def test_remote_jobs_need_none(self):
        remote = AnswerJob(SAMPLE_JOB, None, "remote")
        assert relocation(remote, AnswerSettings(), None).answer.startswith("This role is remote")

    def test_already_local(self):
        a = relocation(JOB, AnswerSettings(), "San Francisco, CA")
        assert a.answer == "I already live in San Francisco, CA, so I would not need to relocate."

    def test_from_settings_or_flagged(self):
        assert relocation(JOB, AnswerSettings(willing_to_relocate=True), "Oakland, CA").answer == (
            "Yes, I am willing to relocate to San Francisco, CA."
        )
        assert relocation(JOB, AnswerSettings(willing_to_relocate=False), None).answer.startswith(
            "No"
        )
        unknown = relocation(JOB, AnswerSettings(), "Denver, CO")
        assert unknown.needs_review and "Please answer this yourself" in unknown.answer


def test_sponsorship_and_work_authorization():
    yes = sponsorship(AnswerSettings(requires_sponsorship=True, visa_status="F-1 OPT"))
    assert yes.answer == "Yes, I will require visa sponsorship (current status: F-1 OPT)."
    assert not yes.needs_review
    # "No" with no authorization stated may just be the default: flagged.
    default_no = sponsorship(AnswerSettings())
    assert default_no.answer.startswith("No") and default_no.needs_review
    stated_no = sponsorship(AnswerSettings(work_authorization="US citizen"))
    assert not stated_no.needs_review
    assert work_authorization(
        AnswerSettings(work_authorization="Green card holder", visa_status="EB-2")
    ).answer == ("Green card holder. Visa status: EB-2.")
    assert work_authorization(AnswerSettings()).needs_review


def test_years_and_skill_experience_come_from_role_dates():
    assert (
        years_experience(SAMPLE_CANDIDATE).answer == "I have 10.5 years of professional experience."
    )
    assert years_experience(CandidateFacts()).needs_review
    resume = sample_resume()
    # "postgres" at Acme counts for PostgreSQL too.
    assert [r.company for r in roles_using(resume, "PostgreSQL")] == [
        "Acme Payments",
        "Beta Logistics",
    ]
    python = skill_experience("Python", resume, True, TODAY)
    # "Built billing APIs in Python ..." describes use: Acme, Mar 2020 - Nov 2026.
    assert python.answer == (
        "About 6.8 years: I have used Python in 1 role (Senior Software Engineer at Acme Payments)."
    )
    assert not python.needs_review
    assert python.evidence[0] == {
        "source": "resume",
        "fact": "Senior Software Engineer at Acme Payments: 1 line describes using Python",
    }
    listed_only = skill_experience("Docker", resume, True, TODAY)
    assert listed_only.needs_review and "among my skills" in listed_only.answer
    missing = skill_experience("Kubernetes", resume, False, TODAY)
    assert missing.answer == "My resume does not list experience with Kubernetes."
    assert missing.needs_review


def test_polish_keeps_only_truthful_rewrites_of_free_text():
    t = tailor(sample_resume(), SAMPLE_JOB, SAMPLE_CANDIDATE)
    result = generate_answers(
        t.content,
        SAMPLE_CANDIDATE,
        JOB,
        AnswerSettings(),
        t.matched_skills,
        t.missing_skills,
        today=TODAY,
    )
    rejected = apply_polish(
        result,
        {
            "why_qualified": "I build billing APIs in Python on AWS for a living.",
            "why_company": "I have run Kubernetes at scale for 9 years.",
            "salary_expectations": "A million dollars.",  # factual answers are never rewritten
        },
        t.content,
        SAMPLE_CANDIDATE,
    )
    by_key = {a.key: a for a in result}
    assert by_key["why_qualified"].source == "llm"
    assert by_key["why_company"].source == "rules"
    assert by_key["salary_expectations"].answer.startswith("I would like to learn more")
    assert len(rejected) == 1 and rejected[0].startswith("why_company")


def test_intent_or_exposure_is_not_counted_as_use():
    from app.agents.relevance import strong_mentions

    assert (
        strong_mentions("Designed APIs for future ML and GenAI integration", "Generative AI") == 0
    )
    assert strong_mentions("Built AI-ready platforms", "AI") == 0
    assert strong_mentions("Exposure to Kubernetes clusters", "Kubernetes") == 0
    assert strong_mentions("Built billing APIs in Python and postgres", "PostgreSQL") == 1
    assert strong_mentions("Wrote Go services; let us go", "Go") == 1  # lowercase "go" is not Go
    resume = sample_resume()
    resume.experience[1].bullets.append("Prototyped designs for future GenAI integration")
    answer = skill_experience("Generative AI", resume, False, TODAY)
    assert answer.needs_review and answer.answer.startswith("My resume mentions Generative AI")
    assert "names Generative AI only as a plan or exposure" in answer.evidence[0]["fact"]
