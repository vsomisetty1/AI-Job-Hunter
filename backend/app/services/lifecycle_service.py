"""Data lifecycle: what generated data is kept, for how long, and cleanup.

Policy (personal use; see ADR-013):

* Uploaded resumes and every parsed/tailored version are kept until the resume
  is deleted; deleting a resume deletes its original file AND the rendered
  PDF/DOCX of all its versions (after the transaction commits).
* A live, approved or submitted package and everything it points to is kept.
* Superseded, rejected and failed packages are deleted after
  PACKAGE_RETENTION_DAYS (default 90), with the tailored resume version and the
  cover letter they created, unless an application or another package still
  points to them. A user can delete such a package (or a generated/reviewed
  one) at once with DELETE /packages/{id}.
* Automation screenshots (automation/) are kept with their submission row and
  become orphans when it goes (its application is deleted).
* Orphaned files (under resumes/, generated/ or automation/, referenced by no row) are
  deleted by the daily sweep once older than ORPHAN_GRACE_HOURS: generation
  writes files just before the rows that point to them, so a younger file may
  simply not be committed yet.

Files are always deleted after the database transaction that dropped their
last reference has committed, and a failed file delete is logged and left
for the sweep; a file is never deleted while a row may still point to it.
"""

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.exceptions import ConflictError, NotFoundError
from app.models.application import Application
from app.models.application_package import ApplicationPackage, a_status
from app.models.application_submission import ApplicationSubmission
from app.models.cover_letter import CoverLetter
from app.models.resume import Resume
from app.models.resume_version import ResumeVersion
from app.storage import StorageBackend

logger = logging.getLogger(__name__)

STORAGE_PREFIXES = ("resumes", "generated", "automation")
PRUNABLE = ("superseded", "rejected", "failed")
DELETABLE = (*PRUNABLE, "generated", "reviewed")


def _paths(*holders: Any) -> list[str]:
    return [p for h in holders if h is not None for p in (h.pdf_path, h.docx_path) if p]


async def referenced_paths(session: AsyncSession) -> set[str]:
    """Every storage path a row points to."""
    paths: set[str] = set(await session.scalars(select(Resume.storage_path)))
    for shots in await session.scalars(select(ApplicationSubmission.screenshots)):
        paths |= {str(s["path"]) for s in shots if isinstance(s, dict) and s.get("path")}
    for column in (ResumeVersion.pdf_path, ResumeVersion.docx_path,
                   CoverLetter.pdf_path, CoverLetter.docx_path):  # fmt: skip
        paths |= {p for p in await session.scalars(select(column).where(column.is_not(None))) if p}
    return paths


async def delete_package_rows(session: AsyncSession, pkg: ApplicationPackage) -> list[str]:
    """Delete a package and the tailored version / cover letter it created when
    nothing else points to them. Returns the file paths to delete AFTER commit."""
    version = (
        await session.get(ResumeVersion, pkg.resume_version_id) if pkg.resume_version_id else None
    )
    letter = await session.get(CoverLetter, pkg.cover_letter_id) if pkg.cover_letter_id else None
    await session.delete(pkg)  # answers cascade
    await session.flush()
    files: list[str] = []
    if version is not None and not await _version_in_use(session, version.id):
        files += _paths(version)
        await session.delete(version)
    if letter is not None and not await _letter_in_use(session, letter.id):
        files += _paths(letter)
        await session.delete(letter)
    await session.flush()
    return files


async def _version_in_use(session: AsyncSession, version_id: uuid.UUID) -> bool:
    used = await session.scalar(
        select(func.count())
        .select_from(ApplicationPackage)
        .where(
            or_(
                ApplicationPackage.resume_version_id == version_id,
                ApplicationPackage.base_resume_version_id == version_id,
            )  # fmt: skip
        )
    )
    used = (used or 0) + (
        await session.scalar(
            select(func.count())
            .select_from(Application)
            .where(Application.resume_version_id == version_id)
        )
        or 0
    )
    return used > 0


async def _letter_in_use(session: AsyncSession, letter_id: uuid.UUID) -> bool:
    used = await session.scalar(
        select(func.count())
        .select_from(ApplicationPackage)
        .where(ApplicationPackage.cover_letter_id == letter_id)
    )
    used = (used or 0) + (
        await session.scalar(
            select(func.count())
            .select_from(Application)
            .where(Application.cover_letter_id == letter_id)
        )
        or 0
    )
    return used > 0


async def resume_file_paths(session: AsyncSession, resume_id: uuid.UUID) -> list[str]:
    """The original upload and every rendered version of one resume."""
    resume = await session.get(Resume, resume_id)
    versions = await session.scalars(
        select(ResumeVersion).where(ResumeVersion.resume_id == resume_id)
    )
    return ([resume.storage_path] if resume else []) + _paths(*versions)


class LifecycleService:
    def __init__(
        self,
        settings: Settings,
        sessionmaker: async_sessionmaker[AsyncSession],
        storage: StorageBackend,
    ) -> None:
        self.settings = settings
        self.sessionmaker = sessionmaker
        self.storage = storage

    async def delete_files(self, paths: list[str]) -> int:
        """Best effort: a file that cannot be deleted now is left for the sweep."""
        deleted = 0
        for path in paths:
            try:
                await self.storage.delete(path)
                deleted += 1
            except Exception:
                logger.exception("could not delete %s; the orphan sweep will retry", path)
        return deleted

    async def delete_package(self, session: AsyncSession, package_id: uuid.UUID) -> list[str]:
        """Inside the caller's transaction; returns paths to delete after commit."""
        pkg = await session.get(ApplicationPackage, package_id, with_for_update=True)
        if pkg is None:
            raise NotFoundError("Package not found", {"package_id": str(package_id)})
        if pkg.status not in DELETABLE:
            raise ConflictError(
                f"{a_status(pkg.status)} package cannot be deleted"
                + (" (reject it first)." if pkg.status == "approved" else ".")
            )
        return await delete_package_rows(session, pkg)

    async def prune_packages(self, *, now: datetime | None = None) -> dict[str, int]:
        """Delete old superseded/rejected/failed packages and their unused artifacts."""
        cutoff = (now or datetime.now(UTC)) - timedelta(days=self.settings.package_retention_days)
        async with self.sessionmaker() as session, session.begin():
            old = list(
                await session.scalars(
                    select(ApplicationPackage)
                    .where(
                        ApplicationPackage.status.in_(PRUNABLE),
                        ApplicationPackage.updated_at < cutoff,
                    )
                    .with_for_update(skip_locked=True)
                )
            )
            files: list[str] = []
            for pkg in old:
                files += await delete_package_rows(session, pkg)
        deleted = await self.delete_files(files)
        result = {"packages": len(old), "files": deleted}
        if old:
            logger.info("pruned old packages", extra=result)
        return result

    async def sweep_orphans(self, *, now: datetime | None = None) -> dict[str, int]:
        """Delete files no row points to, once older than the grace period."""
        now = now or datetime.now(UTC)
        grace = timedelta(hours=self.settings.orphan_grace_hours)
        async with self.sessionmaker() as session:
            referenced = await referenced_paths(session)
        orphans = []
        for prefix in STORAGE_PREFIXES:
            for f in await self.storage.list_files(prefix):
                too_young = f.modified is not None and now - f.modified < grace
                if f.path not in referenced and not too_young:
                    orphans.append(f)
        deleted = await self.delete_files([f.path for f in orphans])
        result = {"orphans": len(orphans), "deleted": deleted,
                  "bytes": sum(f.size for f in orphans)}  # fmt: skip
        if orphans:
            logger.info("swept orphaned files", extra=result)
        return result

    async def report(self) -> dict[str, Any]:
        """Storage use and what the cleanup jobs would act on."""
        now = datetime.now(UTC)
        async with self.sessionmaker() as session:
            referenced = await referenced_paths(session)
            by_status = dict(
                (
                    await session.execute(
                        select(ApplicationPackage.status, func.count()).group_by(
                            ApplicationPackage.status
                        )
                    )
                ).all()  # fmt: skip
            )
            versions = dict(
                (
                    await session.execute(
                        select(ResumeVersion.kind, func.count()).group_by(ResumeVersion.kind)
                    )
                ).all()  # fmt: skip
            )
            letters = await session.scalar(select(func.count()).select_from(CoverLetter))
            cutoff = now - timedelta(days=self.settings.package_retention_days)
            prunable = await session.scalar(
                select(func.count())
                .select_from(ApplicationPackage)
                .where(
                    ApplicationPackage.status.in_(PRUNABLE), ApplicationPackage.updated_at < cutoff
                )
            )
        areas = {}
        orphan_files = orphan_bytes = 0
        for prefix in STORAGE_PREFIXES:
            files = await self.storage.list_files(prefix)
            orphans = [f for f in files if f.path not in referenced]
            orphan_files += len(orphans)
            orphan_bytes += sum(f.size for f in orphans)
            areas[prefix] = {"files": len(files), "bytes": sum(f.size for f in files)}
        return {
            "backend": self.storage.name,
            "areas": areas,
            "orphaned_files": orphan_files,
            "orphaned_bytes": orphan_bytes,
            "packages_by_status": {str(k): int(v) for k, v in by_status.items()},
            "resume_versions_by_kind": {str(k): int(v) for k, v in versions.items()},
            "cover_letters": int(letters or 0),
            "packages_due_for_pruning": int(prunable or 0),
            "policy": {
                "package_retention_days": self.settings.package_retention_days,
                "orphan_grace_hours": self.settings.orphan_grace_hours,
            },
        }

    async def run(self) -> dict[str, Any]:
        """The daily cleanup: prune old packages, then sweep orphaned files."""
        return {"packages": await self.prune_packages(), "files": await self.sweep_orphans()}
