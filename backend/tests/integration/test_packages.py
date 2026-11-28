"""Integration: application package generation and the approval workflow.

Real Postgres (live-pool app: generation runs in a background task with its
own sessions), local file storage in a temp dir, Claude as FakeAnthropic.
"""

import io
import json

import docx
import pdfplumber
import pytest

from app.schemas.package import (
    AnswerRewrite,
    AnswersRewriteOutput,
    BulletRewrite,
    CoverLetterOutput,
    TailoringRewriteOutput,
)
from tests.fixtures.jobs import (
    add_company,
    add_job,
    add_profile,
    add_resume,
    execute,
    fetch,
    fetch_one,
    reset_settings,
    set_settings,
)
from tests.fixtures.resumes import sample_resume

JOB_TEXT = (
    "Stripe builds payments infrastructure. You will design APIs in Python on AWS, own "
    "PostgreSQL data models and run services on Kubernetes."
)
REQUIREMENTS = [
    "5+ years of backend engineering experience",
    "Strong Python and PostgreSQL",
    "Experience with Kubernetes",
]


@pytest.fixture()
async def app(build_live_app, claude):
    await reset_settings()
    app = build_live_app(claude=claude, anthropic_api_key="sk-test")
    yield app
    await reset_settings()


@pytest.fixture()
async def client(app, client_for):
    async with client_for(app) as c:
        yield c


async def seed(**job):
    profile = await add_profile(
        skills=["Python", "PostgreSQL", "AWS", "Java", "Docker", "Go"],
        primary_roles=["Backend Engineer"],
        years_experience=10.5,
        location="Oakland, CA",
    )
    resume_id, version_id = await add_resume(profile, sample_resume().model_dump(mode="json"))
    company = await add_company("Stripe")
    job_id = await add_job(
        company,
        **(
            {
                "title": "Senior Backend Engineer",
                "description": JOB_TEXT,
                "requirements": REQUIREMENTS,
                "location": "San Francisco, CA",
                "salary_min": 180_000,
                "salary_max": 240_000,
            }
            | job
        ),
    )
    return {"profile": profile, "resume": resume_id, "version": version_id, "job": job_id}


async def generate(app, client, job_id, **body) -> dict:
    r = await client.post("/api/v1/packages", json={"job_id": str(job_id), **body})
    assert r.status_code == 202, r.text
    started = r.json()
    info = await app.state.task_manager.wait(started["task_id"], timeout=60)
    detail = (await client.get(f"/api/v1/packages/{started['package_id']}")).json()
    assert info.done, info
    return detail


def pdf_text(data: bytes) -> str:
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        return "\n".join(p.extract_text() or "" for p in pdf.pages)


# ================================================================ generation
async def test_generates_a_complete_package(app, client):
    ids = await seed()
    await set_settings(
        salary_target=200_000, work_authorization="US citizen", willing_to_relocate=True
    )
    pkg = await generate(app, client, ids["job"])

    assert pkg["status"] == "generated" and pkg["version_number"] == 1
    assert pkg["job"]["title"] == "Senior Backend Engineer" and pkg["company_name"] == "Stripe"
    assert pkg["score"] is not None and pkg["score_snapshot"]["method"] == "rules"
    assert pkg["score_snapshot"]["computed_for_package"] is True  # job was never scored
    assert pkg["generation"]["llm_used"] is False

    # Agent 6: tailored resume, every change explained, nothing invented.
    tr = pkg["tailored_resume"]
    assert tr["base_version_id"] == str(ids["version"])
    assert tr["content"]["skills"][:3] == ["Python", "PostgreSQL", "AWS"]
    assert "Kubernetes" not in json.dumps(tr["content"])
    assert tr["tailoring"]["missing_skills"] == ["Kubernetes"]
    assert tr["ats_keywords"] == ["Python", "PostgreSQL", "AWS"]
    # The sample summary already names the role, so it is left as written.
    assert {c["section"] for c in tr["changes"]} >= {"skills", "experience"}
    assert all(c["reason"] and c["at"] for c in tr["changes"])
    assert pkg["base_resume"]["skills"][0] == "Java"  # the original is untouched
    assert tr["has_pdf"] and tr["has_docx"]

    # Agent 8: cover letter.
    cl = pkg["cover_letter"]
    assert cl["method"] == "rules" and 120 <= cl["word_count"] <= 300
    assert "Stripe" in cl["content"] and "Kubernetes" not in cl["content"]

    # Agent 9: answers with evidence; unknowns flagged.
    answers = {a["question_key"]: a for a in pkg["answers"]}
    assert answers["salary_expectations"]["answer"].startswith(
        "My target base salary is USD 200,000"
    )
    assert "within the range in your posting" in answers["salary_expectations"]["answer"]
    assert answers["work_authorization"]["answer"] == "US citizen."
    assert answers["relocation"]["answer"] == "Yes, I am willing to relocate to San Francisco, CA."
    assert answers["sponsorship"]["needs_review"] is False
    assert answers["why_company"]["needs_review"] is True
    assert answers["experience:Kubernetes"]["needs_review"] is True
    assert answers["experience:Python"]["evidence"][0]["source"] == "resume"
    assert pkg["answers_needing_review"] == sum(a["needs_review"] for a in pkg["answers"])

    # Agent 7: files for the tailored and the original resume, and the letter.
    pid = pkg["id"]
    r = await client.get(f"/api/v1/packages/{pid}/files/resume.pdf")
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert "attachment" in r.headers["content-disposition"]
    assert "Jordan_Rivera_Resume_Stripe.pdf" in r.headers["content-disposition"]
    text = pdf_text(r.content)
    assert "Languages: Python, Java, Go" in text and "Other: PostgreSQL, AWS" in text
    assert "Senior Software Engineer — Acme Payments" in text
    original = pdf_text(
        (await client.get(f"/api/v1/packages/{pid}/files/original-resume.pdf")).content
    )
    assert "Languages: Java, Python, Go" in original and "Other: postgres, AWS" in original
    letter = docx.Document(
        io.BytesIO((await client.get(f"/api/v1/packages/{pid}/files/cover-letter.docx")).content)
    )
    assert any("Stripe" in p.text for p in letter.paragraphs)
    assert (await client.get(f"/api/v1/packages/{pid}/files/resume.txt")).status_code == 422

    # Stored where it belongs.
    version = await fetch_one("SELECT * FROM resume_versions WHERE id = :id", id=tr["id"])
    assert version["kind"] == "tailored" and version["job_id"] == ids["job"]
    assert version["version_number"] == 2 and version["target_company"] == "Stripe"
    base = await fetch_one("SELECT * FROM resume_versions WHERE id = :id", id=ids["version"])
    assert base["pdf_path"] and base["docx_path"]
    runs = {r["agent_name"] for r in await fetch("SELECT agent_name FROM agent_runs")}
    assert "application_package" in runs


async def test_one_live_package_per_job_and_missing_inputs(app, client):
    ids = await seed()
    first = await generate(app, client, ids["job"], include_cover_letter=False)
    assert first["cover_letter"] is None
    r = await client.post("/api/v1/packages", json={"job_id": str(ids["job"])})
    assert r.status_code == 409 and r.json()["error"]["details"]["package_id"] == first["id"]

    # A job of a profile without a resume: the package fails with the reason.
    await execute("DELETE FROM resumes")
    other = await add_job(await add_company("Globex"), title="Backend Engineer")
    failed = await generate(app, client, other)
    assert failed["status"] == "failed"
    assert failed["error"] == "Upload a resume first: the package is built from it."

    missing = await client.post(
        "/api/v1/packages", json={"job_id": "00000000-0000-0000-0000-000000000000"}
    )
    assert missing.status_code == 404


async def test_no_profile_is_a_clear_error(client):
    job = await add_job(await add_company())
    r = await client.post("/api/v1/packages", json={"job_id": str(job)})
    assert r.status_code == 422
    assert "Upload a resume first" in r.json()["error"]["message"]


# ================================================================== workflow
async def test_review_approve_submit(app, client):
    ids = await seed()
    pkg = await generate(app, client, ids["job"])
    pid = pkg["id"]

    reviewed = (await client.post(f"/api/v1/packages/{pid}/review")).json()
    assert reviewed["status"] == "reviewed" and reviewed["reviewed_at"]

    # Edit an answer while reviewing.
    answer = next(a for a in reviewed["answers"] if a["question_key"] == "why_company")
    r = await client.patch(
        f"/api/v1/packages/{pid}/answers/{answer['id']}",
        json={"answer": "I have used Stripe for years and admire the API."},
    )
    assert r.status_code == 200
    assert r.json()["source"] == "user" and r.json()["needs_review"] is False

    approved = (
        await client.post(f"/api/v1/packages/{pid}/approve", json={"notes": "Looks good"})
    ).json()
    assert approved["status"] == "approved" and approved["review_notes"] == "Looks good"
    app_row = await fetch_one(
        "SELECT * FROM applications WHERE id = :id", id=approved["application_id"]
    )
    assert app_row["status"] == "ready" and app_row["application_mode"] == "APPROVAL_MODE"
    assert str(app_row["resume_version_id"]) == approved["tailored_resume"]["id"]
    assert str(app_row["cover_letter_id"]) == approved["cover_letter"]["id"]
    assert app_row["approved_at"] is not None and app_row["submitted_at"] is None
    events = [
        e["event_type"]
        for e in await fetch("SELECT event_type FROM application_events ORDER BY created_at")
    ]
    assert events == ["created", "approved"]
    assert (await fetch_one("SELECT status FROM jobs WHERE id = :id", id=ids["job"]))[
        "status"
    ] == "shortlisted"

    # Approved answers are locked.
    r = await client.patch(f"/api/v1/packages/{pid}/answers/{answer['id']}", json={"answer": "x"})
    assert r.status_code == 409
    assert (await client.post(f"/api/v1/packages/{pid}/approve")).status_code == 409

    submitted = (await client.post(f"/api/v1/packages/{pid}/mark-submitted")).json()
    assert submitted["status"] == "submitted" and submitted["submitted_at"]
    app_row = await fetch_one(
        "SELECT * FROM applications WHERE id = :id", id=approved["application_id"]
    )
    assert app_row["status"] == "submitted" and app_row["automation_state"] == "completed"
    assert (await fetch_one("SELECT status FROM jobs WHERE id = :id", id=ids["job"]))[
        "status"
    ] == "applied"
    assert (await client.post(f"/api/v1/packages/{pid}/regenerate")).status_code == 409
    assert (
        await client.post(f"/api/v1/packages/{pid}/reject", json={"reason": "x"})
    ).status_code == 409


async def test_a_package_for_an_expired_job_cannot_be_approved(app, client):
    ids = await seed()
    pkg = await generate(app, client, ids["job"])
    await execute("UPDATE jobs SET status = 'expired', expired_at = now() WHERE id = :id",
                  id=ids["job"])  # fmt: skip
    r = await client.post(f"/api/v1/packages/{pkg['id']}/approve")
    assert r.status_code == 409
    assert "no longer posted" in r.json()["error"]["message"]
    assert await fetch("SELECT id FROM applications") == []


async def test_reject_withdraws_approval_and_regenerate_supersedes(app, client):
    ids = await seed()
    pkg = await generate(app, client, ids["job"])
    pid = pkg["id"]
    approved = (await client.post(f"/api/v1/packages/{pid}/approve")).json()

    rejected = (
        await client.post(
            f"/api/v1/packages/{pid}/reject", json={"reason": "Cover letter too generic"}
        )
    ).json()
    assert (
        rejected["status"] == "rejected"
        and rejected["rejection_reason"] == "Cover letter too generic"
    )
    app_row = await fetch_one(
        "SELECT * FROM applications WHERE id = :id", id=approved["application_id"]
    )
    assert app_row["status"] == "drafted" and app_row["approved_at"] is None
    assert (
        await client.post(f"/api/v1/packages/{pid}/reject", json={"reason": ""})
    ).status_code == 422

    r = await client.post(
        f"/api/v1/packages/{pid}/regenerate", json={"include_cover_letter": False}
    )
    assert r.status_code == 202
    await app.state.task_manager.wait(r.json()["task_id"], timeout=60)
    second = (await client.get(f"/api/v1/packages/{r.json()['package_id']}")).json()
    assert second["status"] == "generated" and second["version_number"] == 2
    assert second["cover_letter"] is None
    # Versions accumulate: two tailored resumes for the job.
    assert len(await fetch("SELECT id FROM resume_versions WHERE kind = 'tailored'")) == 2

    # Regenerating a generated package supersedes it; the old one cannot be regenerated again.
    r = await client.post(f"/api/v1/packages/{second['id']}/regenerate")
    await app.state.task_manager.wait(r.json()["task_id"], timeout=60)
    old = (await client.get(f"/api/v1/packages/{second['id']}")).json()
    assert old["status"] == "superseded"
    assert (await client.post(f"/api/v1/packages/{pid}/regenerate")).status_code == 409

    queue = (
        await client.get("/api/v1/packages", params={"status": ["generated", "reviewed"]})
    ).json()
    assert queue["total"] == 1 and queue["items"][0]["version_number"] == 3
    history = (await client.get("/api/v1/packages", params={"job_id": str(ids["job"])})).json()
    assert [p["status"] for p in history["items"]] == ["generated", "superseded", "rejected"]
    # Every cover letter version is kept.
    assert len(await fetch("SELECT id FROM cover_letters")) == 2


async def test_interrupted_generation_is_marked_failed(app, client):
    from app.scheduler.tasks import INTERRUPTED, recover_interrupted_work

    ids = await seed()
    await execute(
        "INSERT INTO application_packages (job_id, profile_id) VALUES (:j, :p)",
        j=ids["job"],
        p=ids["profile"],
    )
    result = await recover_interrupted_work()
    assert result["packages"] == 1
    row = await fetch_one("SELECT status, error FROM application_packages")
    assert row == {"status": "failed", "error": INTERRUPTED}


# ==================================================================== Claude
async def test_claude_rewording_is_checked_against_the_resume(app, client, claude):
    ids = await seed()
    claude.responses = [
        TailoringRewriteOutput(
            summary="Senior backend engineer building payment APIs in Python on AWS.",
            summary_reason="Leads with payments",
            bullets=[
                BulletRewrite(
                    role=0,
                    index=0,
                    reason="Stronger verb",
                    text=(
                        "Designed and built billing APIs in Python and PostgreSQL serving "
                        "2M requests a day"
                    ),
                ),
                # Invents Kubernetes: dropped.
                BulletRewrite(
                    role=0,
                    index=1,
                    reason="Adds k8s",
                    text="Cut AWS costs by 30% by moving services to Kubernetes",
                ),
                # Invents a number: dropped.
                BulletRewrite(
                    role=0,
                    index=2,
                    reason="Bigger",
                    text="Mentored 12 engineers through onboarding",
                ),
            ],
        ),
        CoverLetterOutput(paragraphs=["Too short, and no company named."]),
        AnswersRewriteOutput(
            answers=[
                AnswerRewrite(
                    key="why_qualified",
                    answer="I have built billing APIs in Python and PostgreSQL that serve 2M "
                    "requests a day, and I have run AWS infrastructure for years.",
                ),
                AnswerRewrite(key="why_company", answer="I know Kubernetes deeply."),
            ]
        ),
    ]
    pkg = await generate(app, client, ids["job"], use_llm=True)
    assert pkg["status"] == "generated", pkg["error"]
    tr = pkg["tailored_resume"]
    assert tr["tailoring"]["method"] == "claude"
    bullets = tr["content"]["experience"][0]["bullets"]
    assert bullets[0].startswith("Designed and built billing APIs")
    assert not any("Kubernetes" in b or "12 engineers" in b for b in bullets)
    assert len(tr["tailoring"]["rejected_rewrites"]) == 2
    assert tr["content"]["summary"].startswith("Senior backend engineer building payment APIs")

    assert pkg["cover_letter"]["method"] == "rules"  # Claude's letter failed the checks
    assert any("not used" in n for n in pkg["cover_letter"]["generation"]["notes"])
    answers = {a["question_key"]: a for a in pkg["answers"]}
    assert answers["why_qualified"]["source"] == "llm"
    assert answers["why_company"]["source"] == "rules"  # invented Kubernetes: kept the draft
    assert pkg["generation"]["llm_used"] is True
    assert len(claude.calls) == 3
    tailoring_call = claude.calls[0]["messages"][0]["content"]
    assert "<resume>" in tailoring_call and "jordan@example.com" not in tailoring_call
    usage = await fetch(
        "SELECT agent_name, input_tokens FROM agent_runs WHERE agent_name LIKE 'agent_%' "
        "ORDER BY started_at"
    )
    assert [u["agent_name"] for u in usage] == [
        "agent_6_resume_tailoring",
        "agent_8_cover_letters",
        "agent_9_application_answers",
    ]
    assert all(u["input_tokens"] == 1000 for u in usage)


async def test_use_llm_without_a_key_falls_back(build_live_app, client_for):
    await reset_settings()
    app = build_live_app()  # no ANTHROPIC_API_KEY
    ids = await seed()
    async with client_for(app) as c:
        pkg = await generate(app, c, ids["job"], use_llm=True)
    assert pkg["status"] == "generated" and pkg["generation"]["llm_used"] is False
    assert any("no ANTHROPIC_API_KEY" in n for n in pkg["tailored_resume"]["tailoring"]["notes"])
