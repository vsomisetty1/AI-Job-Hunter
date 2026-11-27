"""Seed data for filtering and scoring tests (real Postgres, committed rows).

All helpers write through the app's engine (`get_engine()`), so they work with
the live-pool app fixture. User tables are emptied by that fixture; the
settings row is reset by `reset_settings`.
"""

import hashlib
import itertools
import json
import uuid
from typing import Any

from sqlalchemy import text

from app.core.database import get_engine

_counter = itertools.count(1)

DEFAULT_DESCRIPTION = (
    "We build APIs in Python on AWS with PostgreSQL. You will design services, "
    "review code and mentor engineers."
)
DEFAULT_REQUIREMENTS = ["5+ years of backend engineering experience", "Python and PostgreSQL"]


def key(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


async def execute(sql: str, **params: Any) -> None:
    async with get_engine().begin() as conn:
        await conn.execute(text(sql), params)


async def fetch(sql: str, **params: Any) -> list[dict[str, Any]]:
    async with get_engine().connect() as conn:
        return [dict(r._mapping) for r in await conn.execute(text(sql), params)]


async def fetch_one(sql: str, **params: Any) -> dict[str, Any]:
    rows = await fetch(sql, **params)
    assert len(rows) == 1, rows
    return rows[0]


async def add_company(name: str = "Acme Robotics", source: str = "greenhouse") -> uuid.UUID:
    slug = f"{name.lower().replace(' ', '-')}-{next(_counter)}"
    row = await _insert(
        "INSERT INTO companies (name, source, slug) VALUES (:name, :source, :slug) RETURNING id",
        name=name,
        source=source,
        slug=slug,
    )
    return row


async def add_job(company_id: uuid.UUID, **kw: Any) -> uuid.UUID:
    n = next(_counter)
    values: dict[str, Any] = {
        "external_id": str(n),
        "title": "Senior Backend Engineer",
        "location": "San Francisco, CA",
        "remote_type": "hybrid",
        "employment_type": "full_time",
        "salary_min": 180_000,
        "salary_max": 220_000,
        "salary_currency": "USD",
        "description": DEFAULT_DESCRIPTION,
        "requirements": DEFAULT_REQUIREMENTS,
        "url": f"https://jobs.example/{n}",
        "status": "new",
        "first_seen_at": None,
    } | kw
    values.setdefault("dedup_key", None)
    if values["dedup_key"] is None:
        values["dedup_key"] = key(str(company_id), values["title"], str(values["location"]), str(n))
    values["requirements"] = json.dumps(values["requirements"])
    expired = "now()" if values["status"] == "expired" else "NULL"
    seen = ":first_seen_at" if values["first_seen_at"] is not None else "now()"
    return await _insert(
        f"""
        INSERT INTO jobs (company_id, external_id, title, location, remote_type, employment_type,
                          salary_min, salary_max, salary_currency, description, requirements, url,
                          dedup_key, status, expired_at, first_seen_at, last_seen_at)
        VALUES (:company_id, :external_id, :title, :location, :remote_type, :employment_type,
                :salary_min, :salary_max, :salary_currency, :description,
                CAST(:requirements AS jsonb), :url, :dedup_key, :status, {expired}, {seen},
                greatest({seen}, now()))
        RETURNING id
        """,
        company_id=company_id,
        **values,
    )


async def add_profile(**kw: Any) -> uuid.UUID:
    values: dict[str, Any] = {
        "full_name": "Jordan Rivera",
        "skills": ["Python", "PostgreSQL", "Docker", "AWS"],
        "seniority": "senior",
        "years_experience": 7,
        "primary_roles": ["Backend Engineer", "Software Engineer"],
        "related_roles": ["Engineering Manager"],
        "location": "San Francisco, CA",
    } | kw
    return await _insert(
        """
        INSERT INTO candidate_profiles (full_name, skills, seniority, years_experience,
                                        primary_roles, related_roles, location)
        VALUES (:full_name, :skills, :seniority, :years_experience, :primary_roles,
                :related_roles, :location)
        RETURNING id
        """,
        **values,
    )


async def set_settings(**values: Any) -> None:
    sets = ", ".join(f"{k} = :{k}" for k in values)
    await execute(f"UPDATE settings SET {sets} WHERE id = 1", **values)


async def reset_settings() -> None:
    """Back to the column defaults (the row is recreated by the app on demand)."""
    await execute("DELETE FROM settings")
    await execute("INSERT INTO settings (id) VALUES (1)")


async def _insert(sql: str, **params: Any) -> uuid.UUID:
    async with get_engine().begin() as conn:
        value = (await conn.execute(text(sql), params)).scalar_one()
    assert isinstance(value, uuid.UUID)
    return value
