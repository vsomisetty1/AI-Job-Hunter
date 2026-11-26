"""Candidate profile service: read model, manual edits, applying generated builds."""

import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.agent_1_profile_inference import ProfileBuild
from app.core.exceptions import NotFoundError
from app.models.candidate_profile import CandidateProfile
from app.repositories.candidate_profile_repository import CandidateProfileRepository
from app.schemas.candidate_profile import (
    CandidateProfileRead,
    CandidateProfileUpdate,
    InferenceData,
    ProfileData,
    experience_level,
)

logger = logging.getLogger(__name__)

# API field -> where it lives. ("col", name) = table column; ("profile", name) =
# profile JSONB; ("inference", name) = inference JSONB.
FIELD_MAP: dict[str, list[tuple[str, str]]] = {
    "full_name": [("col", "full_name")],
    "email": [("col", "email")],
    "phone": [("col", "phone")],
    "location": [("col", "location")],
    "linkedin_url": [("col", "linkedin_url")],
    "portfolio_url": [("col", "portfolio_url")],
    "seniority": [("col", "seniority")],
    "years_of_experience": [("col", "years_experience")],
    "skills": [("col", "skills")],
    "industries": [("col", "industries")],
    "inferred_roles": [("col", "primary_roles")],
    "transferable_roles": [("col", "related_roles"), ("inference", "transferable_roles")],
    "headline": [("profile", "headline")],
    "summary": [("profile", "summary")],
    "education_summary": [("profile", "education_summary")],
    "certification_summary": [("profile", "certification_summary")],
}
_COLUMN_TO_FIELD = {target: f for f, targets in FIELD_MAP.items() for kind, target in targets
                    if kind == "col"}  # fmt: skip
CONTACT_COLUMNS = {"full_name", "email", "phone", "location", "linkedin_url", "portfolio_url"}


_LIST_COLUMNS_FIELDS = {"skills", "industries", "inferred_roles", "transferable_roles"}


def _column_value(field: str, value: Any) -> Any:
    """API value -> column value (list columns are NOT NULL: null means empty)."""
    if field == "transferable_roles":
        return [r["title"] for r in value or []]
    if field == "years_of_experience":
        return Decimal(str(value)) if value is not None else None
    if field in _LIST_COLUMNS_FIELDS:
        return value or []
    return value


def to_read(p: CandidateProfile) -> CandidateProfileRead:
    data = ProfileData.model_validate(p.profile or {})
    inf = InferenceData.model_validate(p.inference or {})
    return CandidateProfileRead(
        id=p.id,
        full_name=p.full_name,
        email=p.email,
        phone=p.phone,
        location=p.location,
        linkedin_url=p.linkedin_url,
        portfolio_url=p.portfolio_url,
        headline=data.headline,
        summary=data.summary,
        seniority=p.seniority,
        experience_level=p.experience_level,
        years_of_experience=float(p.years_experience) if p.years_experience is not None else None,
        skills=list(p.skills),
        skill_groups=data.skill_groups,
        industries=list(p.industries),
        inferred_roles=list(p.primary_roles),
        transferable_roles=inf.transferable_roles,
        career_history=data.career_history,
        education=data.education,
        education_summary=data.education_summary,
        certifications=data.certifications,
        certification_summary=data.certification_summary,
        projects=data.projects,
        publications=data.publications,
        awards=data.awards,
        languages=data.languages,
        career_analysis=inf.career_analysis,
        inference_source=inf.source,
        inference_model=inf.model,
        inference_status=p.inference_status,
        inference_error=p.inference_error,
        inferred_at=p.inferred_at,
        overrides=inf.overrides,
        warnings=inf.warnings,
        source_resume_id=data.source_resume_id,
        updated_at=p.updated_at,
    )


class ProfileService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = CandidateProfileRepository(session)

    async def get(self) -> CandidateProfile:
        profile = await self.repo.get_active()
        if profile is None:
            raise NotFoundError("No profile yet: upload a resume to create one.")
        return profile

    async def update(self, patch: CandidateProfileUpdate) -> CandidateProfile:
        profile = await self.repo.get_active(for_update=True)
        if profile is None:
            raise NotFoundError("No profile yet: upload a resume to create one.")
        changes = patch.changes()
        if not changes:
            return profile
        columns: dict[str, Any] = {}
        data = dict(profile.profile or {})
        inference = dict(profile.inference or {})
        for field, value in changes.items():
            for kind, target in FIELD_MAP[field]:
                if kind == "col":
                    columns[target] = _column_value(field, value)
                    if field == "years_of_experience":
                        columns["experience_level"] = experience_level(value)
                elif kind == "profile":
                    data[target] = value
                else:
                    inference[target] = value or []
        inference["overrides"] = sorted(set(inference.get("overrides", [])) | set(changes))
        columns.update(profile=data, inference=inference)
        updated = await self.repo.update(profile, columns)
        logger.info("profile edited", extra={"fields": sorted(changes)})
        return updated

    async def mark(self, status: str, error: str | None = None) -> CandidateProfile | None:
        profile = await self.repo.get_active(for_update=True)
        if profile is None:
            return None
        values: dict[str, Any] = {"inference_status": status, "inference_error": error}
        if status == "complete":
            values["inferred_at"] = datetime.now(UTC)
        return await self.repo.update(profile, values)

    async def apply_build(
        self,
        build: ProfileBuild,
        *,
        keep_overrides: bool,
        source_resume_id: str,
        source_version_id: str,
    ) -> CandidateProfile:
        """Write a generated profile, keeping hand-edited fields when asked."""
        profile = await self.repo.get_active(for_update=True)
        if profile is None:
            raise NotFoundError("Profile disappeared during generation.")
        old_inf = InferenceData.model_validate(profile.inference or {})
        old_data = ProfileData.model_validate(profile.profile or {})
        overrides = set(old_inf.overrides) if keep_overrides else set()

        columns: dict[str, Any] = {}
        for column, value in build.columns.items():
            field = _COLUMN_TO_FIELD.get(column)
            if field in overrides:
                continue
            if column in CONTACT_COLUMNS and not value:
                continue  # a resume without e.g. a phone number does not erase it
            columns[column] = value
        years = columns.get("years_experience", profile.years_experience)
        columns["experience_level"] = experience_level(years)

        data = build.profile.model_copy(deep=True)
        data.source_resume_id = source_resume_id
        data.source_version_id = source_version_id
        for field in ("headline", "summary", "education_summary", "certification_summary"):
            if field in overrides:
                setattr(data, field, getattr(old_data, field))

        inference = build.inference.model_copy(deep=True)
        inference.overrides = sorted(overrides)
        if "transferable_roles" in overrides:
            inference.transferable_roles = old_inf.transferable_roles

        columns.update(
            profile=data.model_dump(mode="json"),
            inference=inference.model_dump(mode="json"),
            inference_status="complete",
            inference_error="; ".join(build.llm_errors)[:1000] or None,
            inferred_at=datetime.now(UTC),
        )
        return await self.repo.update(profile, columns)
