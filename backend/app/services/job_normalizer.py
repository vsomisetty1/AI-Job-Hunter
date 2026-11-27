"""NormalizedJob -> jobs table values (source-agnostic)."""

import uuid
from datetime import datetime
from typing import Any

from app.agents.agent_3_deduplication import content_hash, dedup_key
from app.schemas.job import NormalizedJob


def job_values(job: NormalizedJob) -> dict[str, Any]:
    """Columns derived from the posting (shared by insert and update)."""
    return {
        "external_id": job.source_job_id,
        "title": job.title,
        "location": job.location,
        "remote_type": job.remote_type,
        "employment_type": job.employment_type,
        "salary_min": job.salary_min,
        "salary_max": job.salary_max,
        "salary_currency": job.salary_currency,
        "compensation_text": job.compensation_text,
        "description": job.description,
        "requirements": list(job.requirements),
        "url": job.url,
        "apply_url": job.apply_url,
        "posted_at": job.posted_at,
        "dedup_key": dedup_key(job.company_name, job.title, job.location),
        "content_hash": content_hash(job),
        "raw": job.raw,
    }


def insert_values(job: NormalizedJob, company_id: uuid.UUID, seen_at: datetime) -> dict[str, Any]:
    # first/last seen come from the same clock, so last_seen >= first_seen holds.
    return job_values(job) | {
        "company_id": company_id,
        "first_seen_at": seen_at,
        "last_seen_at": seen_at,
    }


def update_values(job: NormalizedJob, seen_at: datetime, *, revive: bool) -> dict[str, Any]:
    values = job_values(job) | {"last_seen_at": seen_at}
    if revive:  # the posting came back after being marked expired
        values |= {"status": "new", "expired_at": None}
    return values
