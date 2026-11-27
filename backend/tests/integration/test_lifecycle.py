"""Integration: data lifecycle (package deletion and retention, resume deletion,
orphaned-file sweep, storage report) on real Postgres and local file storage."""

import os
import time
from datetime import UTC, datetime, timedelta

import pytest

from app.models.application_package import a_status
from tests.fixtures.jobs import (
    add_company,
    add_job,
    add_profile,
    add_resume,
    execute,
    fetch,
    fetch_one,
    reset_settings,
)
from tests.fixtures.resumes import sample_resume


@pytest.fixture()
async def app(build_live_app):
    await reset_settings()
    yield build_live_app()
    await reset_settings()


@pytest.fixture()
async def client(app, client_for):
    async with client_for(app) as c:
        yield c


async def seed():
    profile = await add_profile()
    resume_id, version_id = await add_resume(profile, sample_resume().model_dump(mode="json"))
    job = await add_job(await add_company("Stripe"))
    return {"profile": profile, "resume": resume_id, "version": version_id, "job": job}


async def generate(app, client, job_id) -> dict:
    r = await client.post("/api/v1/packages", json={"job_id": str(job_id)})
    assert r.status_code == 202, r.text
    await app.state.task_manager.wait(r.json()["task_id"], timeout=60)
    return (await client.get(f"/api/v1/packages/{r.json()['package_id']}")).json()


async def regenerate(app, client, package_id) -> dict:
    r = await client.post(f"/api/v1/packages/{package_id}/regenerate")
    assert r.status_code == 202, r.text
    await app.state.task_manager.wait(r.json()["task_id"], timeout=60)
    return (await client.get(f"/api/v1/packages/{r.json()['package_id']}")).json()


def stored(app) -> set[str]:
    root = app.state.storage.root
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}


async def package_files(package_id) -> set[str]:
    row = await fetch_one(
        """SELECT v.pdf_path AS a, v.docx_path AS b, c.pdf_path AS c, c.docx_path AS d
           FROM application_packages p
           LEFT JOIN resume_versions v ON v.id = p.resume_version_id
           LEFT JOIN cover_letters c ON c.id = p.cover_letter_id WHERE p.id = :id""",
        id=package_id,
    )
    return {v for v in row.values() if v}


def test_status_article():
    assert a_status("approved") == "An approved" and a_status("generated") == "A generated"


# ======================================================== package deletion
async def test_deleting_a_superseded_package_removes_its_artifacts_and_files(app, client):
    ids = await seed()
    first = await generate(app, client, ids["job"])
    files = await package_files(first["id"])
    assert len(files) == 4 and files <= stored(app)
    second = await regenerate(app, client, first["id"])

    r = await client.delete(f"/api/v1/packages/{first['id']}")
    assert r.status_code == 204
    assert (await client.get(f"/api/v1/packages/{first['id']}")).status_code == 404
    assert not files & stored(app)
    assert (await fetch_one(
        "SELECT count(*) AS n FROM resume_versions WHERE id = :id",
        id=first["tailored_resume"]["id"]))["n"] == 0  # fmt: skip
    # The newer package, the parsed base version and its renders are untouched.
    assert (await client.get(f"/api/v1/packages/{second['id']}")).json()["status"] == "generated"
    assert await package_files(second["id"]) <= stored(app)
    base = await fetch_one("SELECT * FROM resume_versions WHERE id = :id", id=ids["version"])
    assert base["pdf_path"] in stored(app)


async def test_approved_and_submitted_packages_cannot_be_deleted(app, client):
    ids = await seed()
    pkg = await generate(app, client, ids["job"])
    await client.post(f"/api/v1/packages/{pkg['id']}/approve")
    r = await client.delete(f"/api/v1/packages/{pkg['id']}")
    assert r.status_code == 409
    assert (
        r.json()["error"]["message"] == "An approved package cannot be deleted (reject it first)."
    )
    await client.post(f"/api/v1/packages/{pkg['id']}/mark-submitted")
    assert (await client.delete(f"/api/v1/packages/{pkg['id']}")).status_code == 409
    assert (await client.delete(
        "/api/v1/packages/00000000-0000-0000-0000-000000000000")).status_code == 404  # fmt: skip


async def test_artifacts_an_application_uses_are_kept(app, client):
    ids = await seed()
    pkg = await generate(app, client, ids["job"])
    await client.post(f"/api/v1/packages/{pkg['id']}/approve")
    await client.post(f"/api/v1/packages/{pkg['id']}/reject", json={"reason": "redo"})
    # The application still points at the tailored resume (it went back to drafted).
    await execute(
        "UPDATE applications SET resume_version_id = :v WHERE job_id = :j",
        v=pkg["tailored_resume"]["id"], j=ids["job"],
    )  # fmt: skip
    files = await package_files(pkg["id"])
    assert (await client.delete(f"/api/v1/packages/{pkg['id']}")).status_code == 204
    assert (await client.get(f"/api/v1/packages/{pkg['id']}")).status_code == 404
    # The application still points at the tailored resume and the cover letter
    # (approval attached both): rows and files are kept.
    app_row = await fetch_one("SELECT resume_version_id, cover_letter_id FROM applications")
    assert app_row["resume_version_id"] and app_row["cover_letter_id"]
    assert files <= stored(app)


# ============================================================ retention
async def test_old_superseded_rejected_and_failed_packages_are_pruned(app, client):
    ids = await seed()
    first = await generate(app, client, ids["job"])
    second = await regenerate(app, client, first["id"])
    old_files = await package_files(first["id"])
    # Nothing is old enough yet.
    assert (await app.state.lifecycle.prune_packages()) == {"packages": 0, "files": 0}
    # 200 days on, the superseded package goes; the live one stays.
    result = await app.state.lifecycle.prune_packages(now=datetime.now(UTC) + timedelta(days=200))
    assert result == {"packages": 1, "files": 4}
    assert not old_files & stored(app)
    remaining = await fetch("SELECT id, status FROM application_packages")
    assert [(str(r["id"]), r["status"]) for r in remaining] == [(second["id"], "generated")]


# ================================================================ resumes
async def test_deleting_a_resume_removes_its_original_and_rendered_files(app, client):
    ids = await seed()
    pkg = await generate(app, client, ids["job"])
    upload_path = (await fetch_one("SELECT storage_path FROM resumes"))["storage_path"]
    app.state.storage.root.joinpath(upload_path).parent.mkdir(parents=True, exist_ok=True)
    app.state.storage.root.joinpath(upload_path).write_bytes(b"%PDF-1.4 original")
    rendered = {p for p in stored(app) if p.startswith("generated/resume-versions")}
    assert len(rendered) == 4  # parsed + tailored, PDF + DOCX

    r = await client.delete(f"/api/v1/resumes/{ids['resume']}")
    assert r.status_code == 204
    left = stored(app)
    assert upload_path not in left and not rendered & left
    # The package survives without its resume (the version link is cleared).
    after = (await client.get(f"/api/v1/packages/{pkg['id']}")).json()
    assert after["tailored_resume"] is None and after["cover_letter"] is not None


# ================================================================= orphans
async def test_orphan_sweep_respects_references_and_the_grace_period(app, client):
    ids = await seed()
    pkg = await generate(app, client, ids["job"])
    root = app.state.storage.root
    old = root / "generated" / "cover-letters" / "lost.pdf"
    young = root / "generated" / "cover-letters" / "just-written.pdf"
    old.write_bytes(b"x" * 10)
    young.write_bytes(b"y" * 5)
    two_days_ago = time.time() - 2 * 86400
    os.utime(old, (two_days_ago, two_days_ago))
    referenced = await package_files(pkg["id"])
    for path in referenced:  # make referenced files old too: they must survive
        os.utime(root / path, (two_days_ago, two_days_ago))

    report = await app.state.lifecycle.report()
    assert report["orphaned_files"] == 2 and report["orphaned_bytes"] == 15
    result = await app.state.lifecycle.sweep_orphans()
    assert result == {"orphans": 1, "deleted": 1, "bytes": 10}
    left = stored(app)
    assert "generated/cover-letters/lost.pdf" not in left
    assert "generated/cover-letters/just-written.pdf" in left
    assert referenced <= left
    # Later, the young orphan is old enough too.
    later = await app.state.lifecycle.sweep_orphans(now=datetime.now(UTC) + timedelta(days=2))
    assert later["deleted"] == 1


async def test_storage_report_and_cleanup_endpoints(app, client):
    ids = await seed()
    await generate(app, client, ids["job"])
    report = (await client.get("/api/v1/system/storage")).json()
    assert report["backend"] == "local"
    assert report["areas"]["generated"]["files"] == 6  # 2 resume renders x 2 + letter x 2
    assert report["packages_by_status"] == {"generated": 1}
    assert report["resume_versions_by_kind"] == {"parsed": 1, "tailored": 1}
    assert report["policy"] == {"package_retention_days": 90, "orphan_grace_hours": 24}
    cleanup = (await client.post("/api/v1/system/storage/cleanup")).json()
    assert cleanup == {
        "packages": {"packages": 0, "files": 0},
        "files": {"orphans": 0, "deleted": 0, "bytes": 0},
    }
