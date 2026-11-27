"""A realistic parsed resume and matching profile/job inputs for Phase 7 tests."""

from app.agents.agent_6_resume_tailoring import CandidateFacts, TailoringJob
from app.schemas.parsed_resume import (
    ContactInfo,
    EducationEntry,
    ExperienceEntry,
    ParsedResume,
    ProjectEntry,
    SkillGroup,
)


def sample_resume(**overrides: object) -> ParsedResume:
    data = ParsedResume(
        contact=ContactInfo(
            name="Jordan Rivera",
            email="jordan@example.com",
            phone="+1 415 555 0100",
            location="Oakland, CA",
            linkedin="https://www.linkedin.com/in/jordan",
        ),
        summary="Backend engineer who builds reliable payment systems.",
        experience=[
            ExperienceEntry(
                title="Senior Software Engineer",
                company="Acme Payments",
                location="San Francisco, CA",
                start_date="2020-03",
                is_current=True,
                bullets=[
                    "Mentored 4 engineers through onboarding",
                    "Built billing APIs in Python and postgres serving 2M requests a day",
                    "Cut AWS costs by 30% by right-sizing instances",
                ],
                skills=["Python", "postgres", "AWS"],
            ),
            ExperienceEntry(
                title="Software Engineer",
                company="Beta Logistics",
                location="Austin, TX",
                start_date="2016-06",
                end_date="2020-02",
                bullets=[
                    "Wrote Java services for route planning",
                    "Ran PostgreSQL schema migrations with zero downtime",
                ],
            ),
        ],
        education=[
            EducationEntry(
                institution="UC Davis",
                degree="B.S.",
                field_of_study="Computer Science",
                end_date="2016",
            )
        ],
        skills=["Java", "Docker", "postgres", "Python", "AWS", "Go"],
        skill_groups=[
            SkillGroup(name="Tools", skills=["Docker", "Git"]),
            SkillGroup(name="Languages", skills=["Java", "Python", "Go"]),
        ],
        projects=[
            ProjectEntry(name="dotfiles", description="Personal shell setup"),
            ProjectEntry(
                name="pgwatch",
                technologies=["Python", "PostgreSQL"],
                description="A small PostgreSQL monitoring tool",
            ),
        ],
    )
    return data.model_copy(update=overrides)


SAMPLE_JOB = TailoringJob(
    title="Senior Backend Engineer",
    company_name="Stripe",
    description=(
        "Stripe builds payments infrastructure. You will design APIs in Python on AWS, "
        "own PostgreSQL data models and run services on Kubernetes."
    ),
    requirements=(
        "5+ years of backend engineering experience",
        "Strong Python and PostgreSQL",
        "Experience with Kubernetes",
    ),
)

SAMPLE_CANDIDATE = CandidateFacts(
    skills=("Python", "PostgreSQL", "AWS", "Java", "Docker", "Go"),
    seniority="senior",
    years_experience=10.5,
    roles=("Backend Engineer", "Software Engineer"),
)
