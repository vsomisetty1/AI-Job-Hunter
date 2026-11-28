"""The learning dataset: one record per job you built a package for.

Everything here is read from your own rows: packages (score at the time,
matched and missing skills, cover letter, tailoring method), the resume
version a package was tailored from, the application and its outcome
milestones, the company (platform, the industry YOU set) and whether the
form was filled by automation. Nothing is inferred beyond the job family,
which is a fixed rule over the title (`families.py`).
"""

import hashlib
import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.learning.families import job_family
from app.models.application import Application
from app.models.application_package import ApplicationPackage
from app.models.application_submission import ApplicationSubmission
from app.models.company import Company
from app.models.cover_letter import CoverLetter
from app.models.job import Job
from app.models.resume import Resume
from app.models.resume_version import ResumeVersion

# The package that represents an application: the one sent, else approved, else newest.
_RANK = {"submitted": 0, "approved": 1, "reviewed": 2, "generated": 3, "rejected": 4,
         "superseded": 5, "failed": 6, "generating": 7}  # fmt: skip


@dataclass
class Record:
    job_id: str
    job_title: str
    family: str
    remote_type: str
    company_id: str
    company: str
    industry: str | None
    platform: str
    package_id: str
    package_status: str
    package_versions: int  # how many times the package was generated for this job
    score: int | None
    score_method: str | None
    matched_skills: list[str] = field(default_factory=list)
    missing_skills: list[str] = field(default_factory=list)
    cover_letter: bool = False
    cover_letter_method: str | None = None
    tailoring_method: str | None = None
    tailoring_changes: int = 0
    resume_variant: str | None = None  # "resume.pdf v2": the version the package was built from
    application_id: str | None = None
    applied_via: str | None = None  # automation | manual
    generated_at: datetime | None = None
    approved_at: datetime | None = None
    submitted_at: datetime | None = None
    responded_at: datetime | None = None
    first_interview_at: datetime | None = None
    offer_at: datetime | None = None
    rejected_at: datetime | None = None
    withdrawn_at: datetime | None = None

    @property
    def approved(self) -> bool:
        return self.approved_at is not None or self.submitted

    @property
    def submitted(self) -> bool:
        return self.submitted_at is not None

    @property
    def responded(self) -> bool:
        return self.responded_at is not None

    @property
    def interviewed(self) -> bool:
        return self.first_interview_at is not None

    @property
    def offered(self) -> bool:
        return self.offer_at is not None

    @property
    def rejected(self) -> bool:
        return self.rejected_at is not None


async def load_records(session: AsyncSession) -> list[Record]:
    packages = list(
        await session.scalars(
            select(ApplicationPackage).where(ApplicationPackage.status != "generating")
        )
    )
    if not packages:
        return []
    by_job: dict[uuid.UUID, list[ApplicationPackage]] = {}
    for p in packages:
        by_job.setdefault(p.job_id, []).append(p)
    jobs = {
        j.id: (j, c)
        for j, c in (
            await session.execute(
                select(Job, Company)
                .join(Company, Company.id == Job.company_id)
                .where(Job.id.in_(by_job))
            )
        ).all()
    }
    apps = {
        a.job_id: a
        for a in await session.scalars(select(Application).where(Application.job_id.in_(by_job)))
    }
    chosen = {
        job: min(ps, key=lambda p: (_RANK.get(p.status, 9), -p.version_number))
        for job, ps in by_job.items()
    }
    version_ids = {
        v for p in chosen.values() for v in (p.resume_version_id, p.base_resume_version_id) if v
    }
    versions = {
        v.id: v
        for v in await session.scalars(
            select(ResumeVersion).where(ResumeVersion.id.in_(version_ids))
        )
    } if version_ids else {}  # fmt: skip
    resume_ids = {v.resume_id for v in versions.values()}
    resumes = {
        r.id: r for r in await session.scalars(select(Resume).where(Resume.id.in_(resume_ids)))
    } if resume_ids else {}  # fmt: skip
    letter_ids = {p.cover_letter_id for p in chosen.values() if p.cover_letter_id}
    letters = {
        c.id: c
        for c in await session.scalars(
            select(CoverLetter).where(CoverLetter.id.in_(letter_ids))
        )
    } if letter_ids else {}  # fmt: skip
    automated = set(
        await session.scalars(
            select(ApplicationSubmission.application_id).where(
                ApplicationSubmission.status == "submitted"
            )
        )
    )

    records = []
    for job_id, pkg in chosen.items():
        if job_id not in jobs:
            continue
        job, company = jobs[job_id]
        app = apps.get(job_id)
        snap = pkg.score_snapshot or {}
        tailored = versions.get(pkg.resume_version_id) if pkg.resume_version_id else None
        base = versions.get(pkg.base_resume_version_id) if pkg.base_resume_version_id else None
        letter = letters.get(pkg.cover_letter_id) if pkg.cover_letter_id else None
        variant = None
        if base is not None:
            resume = resumes.get(base.resume_id)
            variant = f"{resume.filename if resume else 'resume'} v{base.version_number}"
        submitted_at = app.submitted_at if app else None
        records.append(
            Record(
                job_id=str(job.id),
                job_title=job.title,
                family=job_family(job.title),
                remote_type=job.remote_type,
                company_id=str(company.id),
                company=company.name,
                industry=company.industry,
                platform=company.source,
                package_id=str(pkg.id),
                package_status=pkg.status,
                package_versions=len(by_job[job_id]),
                score=_int(snap.get("overall")),
                score_method=snap.get("method"),
                matched_skills=[str(s) for s in snap.get("matched_skills") or []],
                missing_skills=[str(s) for s in snap.get("missing_skills") or []],
                cover_letter=letter is not None,
                cover_letter_method=letter.method if letter else None,
                tailoring_method=(tailored.tailoring or {}).get("method") if tailored else None,
                tailoring_changes=len(tailored.changes) if tailored else 0,
                resume_variant=variant,
                application_id=str(app.id) if app else None,
                applied_via=(
                    ("automation" if app.id in automated else "manual")
                    if app and submitted_at
                    else None
                ),  # fmt: skip
                generated_at=min(
                    (p.generated_at for p in by_job[job_id] if p.generated_at), default=None
                ),  # fmt: skip
                approved_at=min(
                    (p.approved_at for p in by_job[job_id] if p.approved_at), default=None
                ),  # fmt: skip
                submitted_at=submitted_at,
                responded_at=app.responded_at if app else None,
                first_interview_at=app.first_interview_at if app else None,
                offer_at=app.offer_at if app else None,
                rejected_at=app.rejected_at if app else None,
                withdrawn_at=app.withdrawn_at if app else None,
            )
        )
    records.sort(key=lambda r: (r.generated_at is None, r.generated_at))
    return records


def _int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except TypeError, ValueError:
        return None


def data_hash(records: list[Record]) -> str:
    """Fingerprint of the inputs (an unchanged history is not snapshotted twice)."""
    payload = json.dumps([asdict(r) for r in records], sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()
