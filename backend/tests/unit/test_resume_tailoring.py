"""Unit: Agent 6 resume tailoring and the truthfulness guard."""

import dataclasses
import random
from datetime import UTC, datetime

from app.agents.agent_6_resume_tailoring import (
    CandidateFacts,
    ResumeTailoringAgent,
    TailoringJob,
    apply_rewrites,
    headline_for,
    tailor,
)
from app.agents.truthfulness import (
    check_tailored,
    check_text,
    facts_from,
    numbers_in,
    resume_text,
)
from app.core.config import Settings
from app.llm.client import ClaudeClient
from app.schemas.package import BulletRewrite, TailoringRewriteOutput
from app.schemas.parsed_resume import ExperienceEntry
from tests.fakes import FakeAnthropic, MemoryLLMCache
from tests.fixtures.resumes import SAMPLE_CANDIDATE, SAMPLE_JOB, sample_resume

NOW = datetime(2026, 11, 27, 12, 0, tzinfo=UTC)


# ------------------------------------------------------------- truthfulness
def test_facts_cover_listed_and_mentioned_skills_and_numbers():
    facts = facts_from(sample_resume())
    assert facts.has_skill("PostgreSQL") and facts.has_skill("postgres")  # alias
    assert facts.has_skill("Go")  # ambiguous, but listed
    assert not facts.has_skill("Kubernetes")
    assert {"2", "30", "4", "2016", "2020"} <= facts.numbers
    assert "Acme Payments" in resume_text(sample_resume())


def test_check_text_flags_new_skills_and_numbers():
    facts = facts_from(sample_resume())
    assert check_text("Built APIs in Python on AWS, cutting costs by 30%", facts) == []
    assert check_text("Ran Kubernetes clusters", facts) == [
        "mentions 'Kubernetes', which the resume does not"
    ]
    assert check_text("Led a team of 12", facts) == [
        "uses the number 12, which the resume does not"
    ]
    assert check_text("Led a team of 12", facts, allow_numbers=["12"]) == []
    # Ambiguous names count only as written by the candidate.
    assert check_text("Let's go build it", facts) == []
    assert numbers_in("$1,200 and 3.5x in 2021.") == {"1200", "3.5", "2021"}


def test_check_tailored_locks_the_structure():
    original = sample_resume()
    assert check_tailored(original, original) == []
    moved = original.model_copy(deep=True)
    moved.experience.reverse()
    assert "roles changed" in check_tailored(original, moved)[0]
    renamed = original.model_copy(deep=True)
    renamed.experience[0].company = "Google"
    assert check_tailored(original, renamed)
    extra = original.model_copy(deep=True)
    extra.skills.append("Kubernetes")
    assert check_tailored(original, extra) == ["adds the skill 'Kubernetes'"]
    padded = original.model_copy(deep=True)
    padded.experience[1].bullets.append("Wrote Java services for route planning")
    assert "role 2 has more bullets than the original" in check_tailored(original, padded)
    # A reworded bullet may not borrow another role's numbers.
    borrowed = original.model_copy(deep=True)
    borrowed.experience[1].bullets[0] = "Wrote Java services, cutting costs by 30%"
    assert check_tailored(original, borrowed) == [
        "role 2: uses the number 30, which the resume does not"
    ]
    contact = original.model_copy(deep=True)
    contact.contact.email = "other@example.com"
    assert check_tailored(original, contact) == ["contact details changed"]


# ------------------------------------------------------------ deterministic
def test_tailoring_reorders_and_respells_without_adding_anything():
    original = sample_resume()
    result = tailor(original, SAMPLE_JOB, SAMPLE_CANDIDATE, now=NOW)
    out = result.content

    assert out.skills == ["Python", "PostgreSQL", "AWS", "Java", "Docker", "Go"]
    assert [g.name for g in out.skill_groups] == ["Languages", "Tools"]
    assert out.skill_groups[0].skills == ["Python", "Java", "Go"]
    assert out.experience[0].bullets[0].startswith("Built billing APIs in Python")
    assert out.experience[1].bullets[0].startswith("Ran PostgreSQL")
    assert [p.name for p in out.projects] == ["pgwatch", "dotfiles"]
    assert out.summary == (
        "Senior Backend Engineer with 10+ years of experience in Python, PostgreSQL and AWS. "
        "Backend engineer who builds reliable payment systems."
    )
    assert result.matched_skills == ["Python", "PostgreSQL", "AWS"]
    assert result.missing_skills == ["Kubernetes"]
    assert "Kubernetes" not in out.model_dump_json()
    assert any("Kubernetes" in n and "Nothing was added" in n for n in result.notes)
    # Same roles, dates, education; same bullets, only reordered.
    assert [(e.title, e.company, e.start_date) for e in out.experience] == [
        (e.title, e.company, e.start_date) for e in original.experience
    ]
    for new, old in zip(out.experience, original.experience, strict=True):
        assert sorted(new.bullets) == sorted(old.bullets)
    assert out.education == original.education and out.contact == original.contact
    assert original.skills[0] == "Java"  # input untouched


def test_every_change_is_recorded_with_reason_section_and_time():
    result = tailor(sample_resume(), SAMPLE_JOB, SAMPLE_CANDIDATE, now=NOW)
    kinds = {(c["section"], c["field"]) for c in result.changes}
    assert kinds >= {
        ("skills", "name"),
        ("skills", "order"),
        ("experience", "bullets"),
        ("projects", "order"),
        ("summary", "text"),
    }
    for c in result.changes:
        assert c["reason"] and c["at"] == NOW.isoformat() and "before" in c and "after" in c
    rename = next(c for c in result.changes if c["field"] == "name")
    assert (rename["before"], rename["after"]) == ("postgres", "PostgreSQL")
    role = next(c for c in result.changes if c["section"] == "experience")
    assert role["item"] == "Senior Software Engineer at Acme Payments"
    assert result.summary == "Tailored by reordering: 8 changes."
    data = result.tailoring_json()
    assert data["method"] == "rules" and data["missing_skills"] == ["Kubernetes"]


def test_nothing_to_change_and_no_matching_skills():
    unrelated = TailoringJob("Pastry Chef", "Bakery", "Croissants.", ("Lamination",))
    result = tailor(
        sample_resume(summary=None),
        unrelated,
        dataclasses.replace(SAMPLE_CANDIDATE, roles=()),
        now=NOW,
    )
    assert result.changes == [] and result.matched_skills == []
    assert result.summary.startswith("No changes needed")
    assert "No skills from the posting were found in your resume." in result.notes


def test_headline_uses_only_profile_facts():
    assert headline_for(SAMPLE_JOB, SAMPLE_CANDIDATE, ["Python"]) == (
        "Senior Backend Engineer with 10+ years of experience in Python."
    )
    junior = CandidateFacts(roles=("Data Analyst",), seniority="junior")
    assert headline_for(SAMPLE_JOB, junior, []) == "Junior Data Analyst."
    assert headline_for(SAMPLE_JOB, CandidateFacts(), ["Python"]) is None


def test_headline_does_not_contradict_years_stated_in_the_summary():
    resume = sample_resume(summary="Backend engineer with 7+ years building payment systems.")
    result = tailor(resume, SAMPLE_JOB, SAMPLE_CANDIDATE, now=NOW)
    assert result.content.summary == (
        "Senior Backend Engineer experienced in Python, PostgreSQL and AWS. "
        "Backend engineer with 7+ years building payment systems."
    )


def test_headline_dropped_if_a_profile_role_names_an_unknown_skill():
    cand = dataclasses.replace(SAMPLE_CANDIDATE, roles=("Kubernetes Engineer",))
    result = tailor(sample_resume(), SAMPLE_JOB, cand, now=NOW)
    assert "Kubernetes" not in (result.content.summary or "")


def test_random_resumes_never_break_truthfulness():
    """Property check: whatever the order of bullets and skills, tailoring passes."""
    rng = random.Random(7)
    words = ["Python", "AWS", "PostgreSQL", "Java", "Go", "Docker", "Excel", "Figma", "C++"]
    for _ in range(40):
        bullets = [
            f"Worked on {rng.choice(words)} and {rng.choice(words)} for {rng.randint(1, 9)} teams"
            for _ in range(rng.randint(0, 5))
        ]
        resume = sample_resume(
            skills=rng.sample(words, rng.randint(0, len(words))),
            experience=[
                ExperienceEntry(
                    title="Engineer",
                    company="X",
                    start_date="2019",
                    bullets=bullets,
                    is_current=True,
                )
            ],
        )
        result = tailor(resume, SAMPLE_JOB, SAMPLE_CANDIDATE, now=NOW)
        assert (
            check_tailored(
                resume, result.content, extra_skills=SAMPLE_CANDIDATE.skills, allow_numbers=["10"]
            )
            == []
        )


# ------------------------------------------------------------------ Claude
def rewrites(*bullets: tuple[int, int, str], summary: str | None = None) -> TailoringRewriteOutput:
    return TailoringRewriteOutput(
        summary=summary,
        bullets=[BulletRewrite(role=r, index=i, text=t, reason="emphasis") for r, i, t in bullets],
    )


def test_claude_rewordings_pass_or_are_dropped():
    original = sample_resume()
    base = tailor(original, SAMPLE_JOB, SAMPLE_CANDIDATE, now=NOW)
    result = apply_rewrites(
        base,
        original,
        rewrites(
            (0, 0, "Designed billing APIs in Python and PostgreSQL serving 2M requests a day"),
            (0, 1, "Cut AWS costs by 45% on Kubernetes"),  # new number and skill
            (0, 2, "Mentored engineers"),
            (9, 0, "role out of range"),
            (0, 0, "duplicate index ignored"),
            summary="Backend engineer focused on payment APIs in Python.",
        ),
        SAMPLE_CANDIDATE,
        model="claude-sonnet-5-5",
        now=NOW,
    )
    assert result.method == "claude" and result.model == "claude-sonnet-5-5"
    bullets = result.content.experience[0].bullets
    assert bullets[0].startswith("Designed billing APIs")
    assert bullets[1] == "Cut AWS costs by 30% by right-sizing instances"
    assert bullets[2] == "Mentored engineers"
    assert result.content.summary == "Backend engineer focused on payment APIs in Python."
    (rejected,) = result.rejected_rewrites
    assert set(rejected["problems"]) == {
        "mentions 'Kubernetes', which the resume does not",
        "uses the number 45, which the resume does not",
    }
    assert any("dropped" in n for n in result.notes)
    assert sum(c["field"] == "bullet" for c in result.changes) == 2


def test_overlong_rewording_and_invented_summary_are_dropped():
    original = sample_resume()
    base = tailor(original, SAMPLE_JOB, SAMPLE_CANDIDATE, now=NOW)
    result = apply_rewrites(
        base,
        original,
        rewrites(
            (0, 2, "Mentored 4 engineers " + "with great care " * 20), summary="Kubernetes expert."
        ),
        SAMPLE_CANDIDATE,
        model="m",
        now=NOW,
    )
    assert len(result.rejected_rewrites) == 2
    assert result.content.summary == base.content.summary


async def test_agent_uses_claude_only_when_asked_and_configured():
    settings = Settings(_env_file=None, database_url="postgresql://u:p@127.0.0.1:1/x")
    fake = FakeAnthropic(responses=[rewrites((0, 2, "Mentored 4 engineers in API design"))])
    agent = ResumeTailoringAgent(ClaudeClient(settings, cache=MemoryLLMCache(), client=fake))
    agent.track = _no_tracking  # type: ignore[method-assign]
    plain = await agent.run(sample_resume(), SAMPLE_JOB, SAMPLE_CANDIDATE, use_llm=False)
    assert plain.method == "rules" and fake.calls == []
    polished = await agent.run(sample_resume(), SAMPLE_JOB, SAMPLE_CANDIDATE, use_llm=True)
    assert polished.method == "claude"
    assert "Mentored 4 engineers in API design" in polished.content.experience[0].bullets
    prompt = fake.calls[0]["messages"][0]["content"]
    assert "jordan@example.com" not in prompt and "Python" in prompt

    offline = ResumeTailoringAgent(ClaudeClient(settings))
    result = await offline.run(sample_resume(), SAMPLE_JOB, SAMPLE_CANDIDATE, use_llm=True)
    assert result.method == "rules"
    assert any("no ANTHROPIC_API_KEY" in n for n in result.notes)


class _Run:
    output_summary: dict[str, object]

    def __init__(self) -> None:
        self.output_summary = {"llm_calls": []}

    def add_usage(self, *_: object) -> None:
        return None


def _no_tracking(**_: object):
    import contextlib

    @contextlib.asynccontextmanager
    async def cm():
        yield _Run()

    return cm()


def test_tailoring_is_deterministic():
    a = tailor(sample_resume(), SAMPLE_JOB, SAMPLE_CANDIDATE, now=NOW)
    b = tailor(sample_resume(), SAMPLE_JOB, SAMPLE_CANDIDATE, now=NOW)
    assert a.content == b.content and a.changes == b.changes
