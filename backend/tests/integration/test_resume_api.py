"""Resume intelligence end to end: upload -> parse -> versions -> profile.

Real database (rolled back per test), real sandboxed extraction, local
storage in a temp dir, and a fake Claude that answers by output schema.
"""

import anthropic
import httpx2
import pytest
from sqlalchemy import text

from app.core.database import get_engine
from app.documents.scanner import ScanResult
from app.llm.prompts import ResumeExtractionOutput
from app.schemas.candidate_profile import (
    CareerAnalysisOutput,
    ProfileInferenceOutput,
    RoleSuggestion,
    SkillExtractionOutput,
)
from app.schemas.parsed_resume import ExperienceEntry
from tests.fakes import FakeResponse
from tests.fixtures import documents as d

PDF_MIME = "application/pdf"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

INFERENCE = ProfileInferenceOutput(
    headline="Backend engineer for data platforms",
    seniority="senior",
    seniority_rationale="Seven years, led migrations.",
    inferred_roles=["Senior Backend Engineer", "Data Platform Engineer"],
    transferable_roles=[RoleSuggestion(title="Engineering Manager", rationale="Mentoring.")],
    industries=["Fintech", "SaaS"],
    education_summary="BS Computer Science, UC Berkeley.",
    certification_summary="AWS Solutions Architect.",
)
CAREER = CareerAnalysisOutput(
    narrative="Steady growth.", trajectory="ascending", strengths=["Scale"], gaps=[],
    recommended_focus=["Staff roles"],
)  # fmt: skip


def answer_by_schema(extraction: ResumeExtractionOutput | None = None):
    """Fake Claude that returns a fixed answer for each output schema."""

    def respond(kwargs):
        schema = kwargs["output_format"]
        return FakeResponse(
            {
                ProfileInferenceOutput: INFERENCE,
                CareerAnalysisOutput: CAREER,
                SkillExtractionOutput: SkillExtractionOutput(
                    technical=["Statistics"], tools=["Tableau"], domains=[], soft_skills=[]
                ),
                ResumeExtractionOutput: extraction or ResumeExtractionOutput(),
            }[schema],
            input_tokens=2000,
            output_tokens=300,
        )

    return respond


async def upload(c, data=None, name="cv.pdf", mime=PDF_MIME, **form):
    return await c.post(
        "/api/v1/resumes",
        files={"file": (name, data if data is not None else d.make_pdf(), mime)},
        data={k: str(v).lower() for k, v in form.items()},
    )


async def wait(app, response):
    task_id = response.json().get("task_id")
    info = await app.state.task_manager.wait(task_id, timeout=60)
    assert info.status == "succeeded", info.error
    return info


async def count(app, sql: str) -> int:
    async with get_engine().connect() as conn:
        return (await conn.execute(text(sql))).scalar()


@pytest.fixture()
def db_app(build_live_app):
    return build_live_app()


@pytest.fixture()
def build_db_app(build_live_app):
    return build_live_app


# --------------------------------------------------------------- without Claude
async def test_upload_parse_version_and_deterministic_profile(db_app, client_for):
    async with client_for(db_app) as c:
        assert (await c.get("/api/v1/profile")).status_code == 404
        r = await upload(c)
        assert r.status_code == 201, r.text
        body = r.json()
        resume = body["resume"]
        assert resume["is_primary"] and resume["parse_status"] == "parsed"
        assert resume["parse_method"] == "deterministic" and resume["file_type"] == "pdf"
        parsed = resume["parsed"]
        assert parsed["contact"]["name"] == "Jordan Rivera"
        assert [e["company"] for e in parsed["experience"]] == ["Acme Corp", "Globex Inc"]
        assert [(v["version_number"], v["kind"], v["source"]) for v in resume["versions"]] == [
            (2, "parsed", "parser"),
            (1, "original", "upload"),
        ]
        await wait(db_app, r)

        p = (await c.get("/api/v1/profile")).json()
        assert p["full_name"] == "Jordan Rivera" and p["email"] == "jordan.rivera@example.com"
        assert p["inference_status"] == "complete" and p["inference_source"] == "deterministic"
        assert p["years_of_experience"] >= 9  # Jun 2017 - today, overlaps merged
        assert p["experience_level"] in {"senior", "expert"}
        assert p["seniority"] == "senior"  # from "Senior Software Engineer"
        assert p["inferred_roles"] == ["Senior Software Engineer", "Software Engineer"]
        assert "Kubernetes" in p["skills"]
        assert p["education_summary"].startswith("B.S. in Computer Science")
        assert p["career_history"][0]["is_current"] is True
        assert p["source_resume_id"] == resume["id"]

    runs = await count(db_app, "SELECT count(*) FROM agent_runs WHERE status = 'succeeded'")
    assert runs >= 2  # parser + profile


async def test_docx_upload_and_listing(db_app, client_for):
    async with client_for(db_app) as c:
        r = await upload(c, d.make_docx(contact_in_header=True), "cv.docx", DOCX_MIME)
        assert r.status_code == 201, r.text
        assert r.json()["resume"]["parsed"]["contact"]["phone"] == "(415) 555-0142"
        await wait(db_app, r)
        listed = (await c.get("/api/v1/resumes")).json()
        assert [x["file_type"] for x in listed] == ["docx"]


async def test_duplicate_upload_conflicts(db_app, client_for):
    data = d.make_pdf()  # identical bytes (reportlab stamps a creation time)
    async with client_for(db_app) as c:
        first = await upload(c, data)
        await wait(db_app, first)
        again = await upload(c, data, "renamed.pdf")
    assert again.status_code == 409
    assert again.json()["error"]["details"]["resume_id"] == first.json()["resume"]["id"]


@pytest.mark.parametrize(
    ("data", "name", "mime", "code", "error"),
    [
        (b"just text", "cv.txt", "text/plain", 415, "unsupported_file_type"),
        (d.javascript_pdf(), "cv.pdf", PDF_MIME, 422, "invalid_file"),
        (d.macro_docx(), "cv.docx", DOCX_MIME, 422, "invalid_file"),
        (d.make_pdf(encrypt_password="pw"), "cv.pdf", PDF_MIME, 422, "invalid_file"),
    ],
)
async def test_rejected_uploads_store_nothing(db_app, client_for, data, name, mime, code, error):
    async with client_for(db_app) as c:
        r = await upload(c, data, name, mime)
    assert r.status_code == code, r.text
    assert r.json()["error"]["code"] == error
    assert await count(db_app, "SELECT count(*) FROM resumes") == 0
    assert not any((db_app.state.storage.root).rglob("*.*"))


async def test_upload_size_limits(build_db_app, client_for):
    app = build_db_app(max_upload_mb=0.01)  # ~10 KB file limit, body cap ~1 MB more
    async with client_for(app) as c:
        # Over the file limit: rejected by validation.
        r = await upload(c, b"%PDF-1.4\n" + b"0" * 20_000)
        assert r.status_code == 413 and r.json()["error"]["code"] == "file_too_large"
        # Over the request-body cap: rejected before the body is read.
        r = await upload(c, b"%PDF-1.4\n" + b"0" * 1_200_000)
        assert r.status_code == 413
        assert r.json()["error"]["details"]["max_bytes"] == 10485 + 1024 * 1024
    assert await count(app, "SELECT count(*) FROM resumes") == 0


async def test_infected_upload_rejected(db_app, client_for):
    class Infected:
        name = "clamd"

        async def scan(self, data):
            return ScanResult(clean=False, signature="Eicar-Test-Signature", scanner="clamd")

    db_app.state.scanner = Infected()
    async with client_for(db_app) as c:
        r = await upload(c)
    assert r.status_code == 422 and r.json()["error"]["code"] == "malware_detected"
    assert await count(db_app, "SELECT count(*) FROM resumes") == 0


async def test_download_is_an_attachment(db_app, client_for):
    data = d.make_pdf()
    async with client_for(db_app) as c:
        r = await upload(c, data, "My CV (2026).pdf")
        await wait(db_app, r)
        dl = await c.get(f"/api/v1/resumes/{r.json()['resume']['id']}/download")
    assert dl.status_code == 200 and dl.content == data
    assert dl.headers["content-type"] == PDF_MIME
    assert dl.headers["content-disposition"].startswith('attachment; filename="My CV (2026).pdf"')
    assert dl.headers["x-content-type-options"] == "nosniff"


async def test_edit_parsed_creates_version(db_app, client_for):
    async with client_for(db_app) as c:
        r = await upload(c)
        await wait(db_app, r)
        resume = r.json()["resume"]
        edited = resume["parsed"]
        edited["contact"]["name"] = "Jordan A. Rivera"
        edited["skills"].append("Rust")
        put = await c.put(
            f"/api/v1/resumes/{resume['id']}/parsed",
            json={"data": edited, "change_summary": "Added Rust"},
        )
        assert put.status_code == 201, put.text
        v = put.json()
        assert (v["version_number"], v["kind"], v["source"]) == (3, "parsed", "user_edit")
        assert v["content"]["meta"]["method"] == "user_edit"
        detail = (await c.get(f"/api/v1/resumes/{resume['id']}")).json()
        assert detail["parsed"]["contact"]["name"] == "Jordan A. Rivera"
        assert detail["parsed_version_id"] == v["id"]
        # The original parse is still in the history.
        v2 = next(x for x in detail["versions"] if x["version_number"] == 2)
        old = (await c.get(f"/api/v1/resumes/{resume['id']}/versions/{v2['id']}")).json()
        assert old["content"]["contact"]["name"] == "Jordan Rivera"

        too_big = dict(edited, summary="x" * 6000)
        bad = await c.put(f"/api/v1/resumes/{resume['id']}/parsed", json={"data": too_big})
        assert bad.status_code == 422


async def test_tailored_versions(db_app, client_for):
    async with client_for(db_app) as c:
        r = await upload(c)
        await wait(db_app, r)
        rid = r.json()["resume"]["id"]
        content = r.json()["resume"]["parsed"]
        ok = await c.post(
            f"/api/v1/resumes/{rid}/versions/tailored",
            json={
                "target_role": "Staff Engineer",
                "target_company": "Initech",
                "content": content,
                "ats_keywords": ["Kafka"],
            },  # fmt: skip
        )
        assert ok.status_code == 201, ok.text
        v = ok.json()
        assert (v["kind"], v["target_role"], v["target_company"]) == (
            "tailored",
            "Staff Engineer",
            "Initech",
        )
        no_target = await c.post(
            f"/api/v1/resumes/{rid}/versions/tailored", json={"content": content}
        )
        assert no_target.status_code == 422
        bad_job = await c.post(
            f"/api/v1/resumes/{rid}/versions/tailored",
            json={"job_id": "00000000-0000-0000-0000-000000000000", "content": content},
        )
        assert bad_job.status_code == 404


async def test_primary_switch_and_delete(db_app, client_for):
    async with client_for(db_app) as c:
        a = await upload(c)
        await wait(db_app, a)
        b = await upload(c, d.make_docx(), "b.docx", DOCX_MIME)
        await wait(db_app, b)
        a_id, b_id = a.json()["resume"]["id"], b.json()["resume"]["id"]
        assert not b.json()["resume"]["is_primary"]

        sw = await c.post(f"/api/v1/resumes/{b_id}/primary")
        assert sw.status_code == 202
        await wait(db_app, sw)
        assert (await c.get("/api/v1/profile")).json()["source_resume_id"] == b_id

        stored = list(db_app.state.storage.root.rglob("*.docx"))
        assert len(stored) == 1
        assert (await c.delete(f"/api/v1/resumes/{b_id}")).status_code == 204
        assert not stored[0].exists()  # file removed with the row
        # The profile was built from the deleted primary: it is rebuilt from `a`.
        rebuild = db_app.state.task_manager.list_tasks()[0]
        assert rebuild.name == "profile-generation"
        await db_app.state.task_manager.wait(rebuild.id, timeout=60)
        assert (await c.get("/api/v1/profile")).json()["source_resume_id"] == a_id
        remaining = (await c.get("/api/v1/resumes")).json()
        assert [(x["id"], x["is_primary"]) for x in remaining] == [(a_id, True)]
        assert (await c.get(f"/api/v1/resumes/{b_id}")).status_code == 404


async def test_profile_edits_survive_regeneration(db_app, client_for):
    async with client_for(db_app) as c:
        await wait(db_app, await upload(c))
        patch = await c.patch(
            "/api/v1/profile", json={"headline": "My own headline", "inferred_roles": ["SRE"]}
        )
        assert patch.status_code == 200, patch.text
        assert sorted(patch.json()["overrides"]) == ["headline", "inferred_roles"]

        regen = await c.post("/api/v1/profile/regenerate", json={})
        assert regen.status_code == 202
        await wait(db_app, regen)
        p = (await c.get("/api/v1/profile")).json()
        assert p["headline"] == "My own headline" and p["inferred_roles"] == ["SRE"]

        regen = await c.post("/api/v1/profile/regenerate", json={"keep_overrides": False})
        await wait(db_app, regen)
        p = (await c.get("/api/v1/profile")).json()
        assert p["inferred_roles"] == ["Senior Software Engineer", "Software Engineer"]
        assert p["overrides"] == []

        bad = await c.patch("/api/v1/profile", json={"email": "not-an-email"})
        assert bad.status_code == 422


# ------------------------------------------------------------------ with Claude
async def test_claude_profile_generation_and_cache(build_db_app, client_for, claude):
    claude.responses = [answer_by_schema()] * 10
    app = build_db_app(claude=claude)
    async with client_for(app) as c:
        await wait(app, await upload(c))
        # Clean parse: no resume_parse call. Profile: inference + career (parallel).
        schemas = sorted(call["output_format"].__name__ for call in claude.calls)
        assert schemas == ["CareerAnalysisOutput", "ProfileInferenceOutput"]
        # Claude sees no personal data.
        sent = " ".join(call["messages"][0]["content"] for call in claude.calls)
        assert "Jordan" not in sent and "@example.com" not in sent and "555" not in sent

        p = (await c.get("/api/v1/profile")).json()
        assert p["inference_source"] == "llm" and p["seniority"] == "senior"
        assert p["inferred_roles"] == INFERENCE.inferred_roles
        assert p["transferable_roles"][0]["title"] == "Engineering Manager"
        assert p["industries"] == ["Fintech", "SaaS"]
        assert p["career_analysis"]["trajectory"] == "ascending"
        assert p["headline"] == INFERENCE.headline

        regen = await c.post("/api/v1/profile/regenerate", json={})
        await wait(app, regen)
        assert len(claude.calls) == 2  # same input: answered from the cache

    cost = await count(app, "SELECT sum(cost_usd) * 1000000 FROM agent_runs")
    assert cost == 2 * (2000 * 4 + 300 * 20)  # two calls, Opus 5.5 pricing (micro-dollars)
    assert await count(app, "SELECT count(*) FROM llm_cache_entries") == 2


async def test_claude_fills_weak_sections_only(build_db_app, client_for, claude):
    blocks = [
        ("name", "Sam Lee"),
        ("text", "sam@example.com"),
        ("heading", "EXPERIENCE"),
        ("text", "Did many things for many years with many people"),
        ("text", "and other things too"),
        ("heading", "SKILLS"),
        ("text", "Python, SQL"),
    ]
    extraction = ResumeExtractionOutput(
        experience=[
            ExperienceEntry(
                title="Data Analyst",
                company="Initech",
                start_date="2020-01",
                is_current=True,
                bullets=["Built dashboards"],
            )
        ]  # fmt: skip
    )
    claude.responses = [answer_by_schema(extraction)] * 10
    app = build_db_app(claude=claude)
    async with client_for(app) as c:
        r = await upload(c, d.make_pdf(blocks))
        await wait(app, r)
        parse_call = next(x for x in claude.calls if x["output_format"] is ResumeExtractionOutput)
        content = parse_call["messages"][0]["content"]
        assert "Extract these sections and leave every other field null: experience" in content
        assert "Python, SQL" not in content  # only the weak section is sent
        assert any(x["output_format"] is SkillExtractionOutput for x in claude.calls)  # few skills

        detail = (await c.get(f"/api/v1/resumes/{r.json()['resume']['id']}")).json()
        assert detail["parse_method"] == "llm_assisted"
        assert detail["parsed"]["experience"][0]["company"] == "Initech"
        assert detail["parsed"]["meta"]["llm_sections"] == ["experience"]
        assert detail["versions"][0]["change_summary"].startswith("AI-assisted")
        p = (await c.get("/api/v1/profile")).json()
        assert "Tableau" in p["skills"]


async def test_claude_outage_falls_back_to_deterministic(build_db_app, client_for, claude):
    def rate_limited(_):
        req = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
        return anthropic.RateLimitError(
            "slow down", response=httpx2.Response(429, request=req), body=None
        )

    claude.responses = [rate_limited] * 10
    app = build_db_app(claude=claude)
    async with client_for(app) as c:
        await wait(app, await upload(c))
        p = (await c.get("/api/v1/profile")).json()
    assert p["inference_status"] == "complete" and p["inference_source"] == "deterministic"
    assert p["inferred_roles"] == ["Senior Software Engineer", "Software Engineer"]
    assert "rate limit" in p["inference_error"]
    assert any("unavailable" in w for w in p["warnings"])


async def test_reparse_creates_new_version(db_app, client_for):
    async with client_for(db_app) as c:
        r = await upload(c)
        await wait(db_app, r)
        rid = r.json()["resume"]["id"]
        rp = await c.post(f"/api/v1/resumes/{rid}/reparse", json={"use_llm": False})
        assert rp.status_code == 202
        await wait(db_app, rp)
        versions = (await c.get(f"/api/v1/resumes/{rid}/versions")).json()
    assert [v["kind"] for v in versions] == ["parsed", "parsed", "original"]
    assert versions[0]["change_summary"] == "Re-parsed"


async def test_restart_recovers_interrupted_work(db_app, client_for):
    from app.scheduler.tasks import INTERRUPTED, recover_interrupted_work

    async with client_for(db_app) as c:
        await wait(db_app, await upload(c))
        async with get_engine().begin() as conn:
            await conn.execute(text("UPDATE candidate_profiles SET inference_status = 'running'"))
            await conn.execute(
                text("INSERT INTO agent_runs (agent_name, status) VALUES ('stuck', 'running')")
            )
            await conn.execute(text("INSERT INTO discovery_runs (trigger) VALUES ('manual')"))
        assert await recover_interrupted_work() == {
            "profiles": 1,
            "agent_runs": 1,
            "discovery_runs": 1,
        }
        p = (await c.get("/api/v1/profile")).json()
    assert (p["inference_status"], p["inference_error"]) == ("failed", INTERRUPTED)
    assert await count(db_app, "SELECT count(*) FROM agent_runs WHERE status = 'running'") == 0
    assert (
        await count(db_app, "SELECT string_agg(status || ':' || error, ',') FROM discovery_runs")
        == f"cancelled:{INTERRUPTED}"
    )
    async with get_engine().begin() as conn:
        await conn.execute(text("DELETE FROM discovery_runs"))


async def test_maintenance_prunes_expired_cache_and_old_runs(db_app):
    from app.scheduler.tasks import run_maintenance

    async with get_engine().begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO llm_cache_entries (cache_key, purpose, model, response, expires_at) "
                "VALUES (repeat('a', 64), 'x', 'm', '{}', now() - interval '1 day'), "
                "(repeat('b', 64), 'x', 'm', '{}', now() + interval '1 day'), "
                "(repeat('c', 64), 'x', 'm', '{}', NULL)"
            )
        )
        await conn.execute(
            text(
                "INSERT INTO agent_runs (agent_name, status, started_at, finished_at) VALUES "
                "('old', 'succeeded', now() - interval '400 days', now() - interval '400 days'), "
                "('new', 'succeeded', now(), now())"
            )
        )
        await conn.execute(
            text(
                "INSERT INTO discovery_runs (trigger, status, started_at, finished_at) VALUES "
                "('scheduled', 'succeeded', now() - interval '400 days', now()), "
                "('manual', 'succeeded', now(), now())"
            )
        )
    result = await run_maintenance(db_app.state.settings)
    assert result == {"llm_cache_entries": 1, "agent_runs": 1, "discovery_runs": 1}
    assert await count(db_app, "SELECT string_agg(trigger, ',') FROM discovery_runs") == "manual"
    async with get_engine().begin() as conn:
        await conn.execute(text("DELETE FROM discovery_runs"))
    assert await count(db_app, "SELECT count(*) FROM llm_cache_entries") == 2
    assert await count(db_app, "SELECT string_agg(agent_name, ',') FROM agent_runs") == "new"


async def test_profile_builds_never_overlap(db_app, client_for):
    """Concurrent regenerations run one at a time (no interleaved writes)."""
    import asyncio

    processor = db_app.state.processor
    real_run = processor.profiler.run
    active = peak = 0

    async def slow_run(*args, **kwargs):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.05)
        try:
            return await real_run(*args, **kwargs)
        finally:
            active -= 1

    async with client_for(db_app) as c:
        await wait(db_app, await upload(c))
    processor.profiler.run = slow_run
    await asyncio.gather(*(processor.generate_profile() for _ in range(3)))
    assert peak == 1
