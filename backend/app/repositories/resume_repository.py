"""Resume and resume-version repositories."""

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import func, select, update

from app.models.resume import Resume
from app.models.resume_version import ResumeVersion
from app.repositories.base import Repository


class ResumeRepository(Repository[Resume]):
    model = Resume

    async def list_for_profile(self, profile_id: uuid.UUID) -> Sequence[Resume]:
        stmt = (
            select(Resume)
            .where(Resume.profile_id == profile_id)
            .order_by(Resume.is_primary.desc(), Resume.created_at.desc())
        )
        return (await self.session.scalars(stmt)).all()

    async def get_by_hash(self, profile_id: uuid.UUID, content_hash: str) -> Resume | None:
        return await self.session.scalar(
            select(Resume).where(
                Resume.profile_id == profile_id, Resume.content_hash == content_hash
            )
        )

    async def get_primary(self, profile_id: uuid.UUID) -> Resume | None:
        return await self.session.scalar(
            select(Resume).where(Resume.profile_id == profile_id, Resume.is_primary.is_(True))
        )

    async def count_for_profile(self, profile_id: uuid.UUID) -> int:
        total = await self.session.scalar(
            select(func.count()).select_from(Resume).where(Resume.profile_id == profile_id)
        )
        return int(total or 0)

    async def clear_primary(self, profile_id: uuid.UUID) -> None:
        # Flush first so the partial unique index never sees two primaries.
        await self.session.execute(
            update(Resume)
            .where(Resume.profile_id == profile_id, Resume.is_primary.is_(True))
            .values(is_primary=False)
        )

    async def lock(self, resume_id: uuid.UUID) -> Resume | None:
        """Row lock: serialises version numbering for one resume."""
        return await self.session.scalar(
            select(Resume).where(Resume.id == resume_id).with_for_update()
        )


class ResumeVersionRepository(Repository[ResumeVersion]):
    model = ResumeVersion

    async def list_for_resume(self, resume_id: uuid.UUID) -> Sequence[ResumeVersion]:
        stmt = (
            select(ResumeVersion)
            .where(ResumeVersion.resume_id == resume_id)
            .order_by(ResumeVersion.version_number.desc())
        )
        return (await self.session.scalars(stmt)).all()

    async def latest(self, resume_id: uuid.UUID, kind: str) -> ResumeVersion | None:
        stmt = (
            select(ResumeVersion)
            .where(ResumeVersion.resume_id == resume_id, ResumeVersion.kind == kind)
            .order_by(ResumeVersion.version_number.desc())
            .limit(1)
        )
        return await self.session.scalar(stmt)

    async def get_for_resume(
        self, resume_id: uuid.UUID, version_id: uuid.UUID
    ) -> ResumeVersion | None:
        return await self.session.scalar(
            select(ResumeVersion).where(
                ResumeVersion.id == version_id, ResumeVersion.resume_id == resume_id
            )
        )

    async def create_next(self, resume_id: uuid.UUID, **values: Any) -> ResumeVersion:
        """Append a version with the next number. Caller must hold the resume lock."""
        current = await self.session.scalar(
            select(func.max(ResumeVersion.version_number)).where(
                ResumeVersion.resume_id == resume_id
            )
        )
        version = ResumeVersion(resume_id=resume_id, version_number=(current or 0) + 1, **values)
        return await self.add(version)
