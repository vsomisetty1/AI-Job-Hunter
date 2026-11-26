"""Candidate profile repository (single active profile)."""

from sqlalchemy import select

from app.models.candidate_profile import CandidateProfile
from app.repositories.base import Repository


class CandidateProfileRepository(Repository[CandidateProfile]):
    model = CandidateProfile

    async def get_active(self, *, for_update: bool = False) -> CandidateProfile | None:
        stmt = select(CandidateProfile).where(CandidateProfile.is_active.is_(True))
        if for_update:
            stmt = stmt.with_for_update()
        return await self.session.scalar(stmt)

    async def get_or_create_active(self, full_name: str) -> CandidateProfile:
        profile = await self.get_active(for_update=True)
        if profile is None:
            profile = await self.add(CandidateProfile(full_name=full_name))
        return profile
