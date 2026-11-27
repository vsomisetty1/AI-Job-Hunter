"""Resume service: upload, versions, edits, download, delete (request-scoped)."""

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.agent_0_resume_parser import ResumeParserAgent
from app.core.config import Settings
from app.core.exceptions import ConflictError, NotFoundError
from app.documents.sandbox import extract_document
from app.documents.scanner import MalwareDetectedError, VirusScanner
from app.documents.validation import CONTENT_TYPES, validate_upload
from app.models.resume import Resume
from app.models.resume_version import ResumeVersion
from app.repositories.candidate_profile_repository import CandidateProfileRepository
from app.repositories.resume_repository import ResumeRepository, ResumeVersionRepository
from app.schemas.parsed_resume import ParsedResume
from app.schemas.resume import TailoredVersionCreate
from app.storage import StorageBackend

logger = logging.getLogger(__name__)

PLACEHOLDER_NAME = "Unnamed candidate"


@dataclass
class UploadResult:
    resume: Resume
    parsed: ParsedResume
    parsed_version: ResumeVersion


class ResumeService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        settings: Settings,
        storage: StorageBackend,
        scanner: VirusScanner,
        parser: ResumeParserAgent,
    ) -> None:
        self.session = session
        self.settings = settings
        self.storage = storage
        self.scanner = scanner
        self.parser = parser
        self.resumes = ResumeRepository(session)
        self.versions = ResumeVersionRepository(session)
        self.profiles = CandidateProfileRepository(session)

    # ------------------------------------------------------------- upload
    async def upload(
        self, data: bytes, filename: str | None, *, make_primary: bool
    ) -> UploadResult:
        checked = validate_upload(data, filename, max_bytes=self.settings.max_upload_bytes)
        scan = await self.scanner.scan(data)
        if not scan.clean:
            logger.warning("upload rejected by antivirus: %s", scan.signature)
            raise MalwareDetectedError(
                "The file was flagged by the virus scanner and was not stored.",
                {"signature": scan.signature},
            )
        doc = await extract_document(
            checked.file_type,
            data,
            max_pages=self.settings.max_pdf_pages,
            timeout_seconds=self.settings.parse_timeout_seconds,
            memory_mb=self.settings.parse_memory_limit_mb,
        )
        # Fast deterministic parse now; Claude enrichment runs in the background.
        parsed = await self.parser.run(doc, use_llm=False)

        profile = await self.profiles.get_or_create_active(parsed.contact.name or PLACEHOLDER_NAME)
        existing = await self.resumes.get_by_hash(profile.id, checked.sha256)
        if existing is not None:
            raise ConflictError(
                "This resume has already been uploaded.", {"resume_id": str(existing.id)}
            )

        is_first = await self.resumes.count_for_profile(profile.id) == 0
        primary = make_primary or is_first
        if primary:
            await self.resumes.clear_primary(profile.id)

        path = f"resumes/{profile.id}/{uuid.uuid4().hex}.{checked.file_type}"
        await self.storage.put(path, data, checked.content_type)
        try:
            resume = await self.resumes.add(
                Resume(
                    profile_id=profile.id,
                    filename=checked.filename,
                    file_type=checked.file_type,
                    storage_path=path,
                    content_hash=checked.sha256,
                    size_bytes=checked.size_bytes,
                    raw_text=doc.text,
                    parse_status="parsed",
                    parse_method="deterministic",
                    parsed_at=datetime.now(UTC),
                    is_primary=primary,
                )
            )
            await self.versions.create_next(
                resume.id,
                kind="original",
                source="upload",
                content={
                    "filename": checked.filename,
                    "file_type": checked.file_type,
                    "size_bytes": checked.size_bytes,
                    "sha256": checked.sha256,
                    "storage_path": path,
                    "page_count": doc.page_count,
                    "virus_scan": scan.scanner,
                },
            )
            parsed_version = await self.versions.create_next(
                resume.id,
                kind="parsed",
                source="parser",
                content=parsed.model_dump(mode="json"),
                change_summary="Parsed from upload",
            )
        except BaseException:
            # The row was not written: do not leave an orphaned file behind.
            await self._delete_file_quietly(path)
            raise
        logger.info(
            "resume uploaded", extra={"resume_id": str(resume.id), "type": checked.file_type}
        )
        return UploadResult(resume, parsed, parsed_version)

    # -------------------------------------------------------------- reads
    async def get(self, resume_id: uuid.UUID) -> Resume:
        resume = await self.resumes.get(resume_id)
        if resume is None:
            raise NotFoundError("Resume not found", {"resume_id": str(resume_id)})
        return resume

    async def list_resumes(self) -> list[Resume]:
        profile = await self.profiles.get_active()
        return [] if profile is None else list(await self.resumes.list_for_profile(profile.id))

    async def latest_parsed(self, resume_id: uuid.UUID) -> ResumeVersion | None:
        return await self.versions.latest(resume_id, "parsed")

    async def list_versions(self, resume_id: uuid.UUID) -> list[ResumeVersion]:
        await self.get(resume_id)
        return list(await self.versions.list_for_resume(resume_id))

    async def get_version(self, resume_id: uuid.UUID, version_id: uuid.UUID) -> ResumeVersion:
        version = await self.versions.get_for_resume(resume_id, version_id)
        if version is None:
            raise NotFoundError("Resume version not found", {"version_id": str(version_id)})
        return version

    async def download(self, resume_id: uuid.UUID) -> tuple[bytes, str, str]:
        resume = await self.get(resume_id)
        data = await self.storage.get(resume.storage_path)
        return data, resume.filename, CONTENT_TYPES[resume.file_type]  # type: ignore[index]

    # ------------------------------------------------------------- writes
    async def set_primary(self, resume_id: uuid.UUID) -> Resume:
        resume = await self.get(resume_id)
        if not resume.is_primary:
            await self.resumes.clear_primary(resume.profile_id)
            await self.session.flush()
            resume = await self.resumes.update(resume, {"is_primary": True})
        return resume

    async def update_parsed(
        self, resume_id: uuid.UUID, data: ParsedResume, change_summary: str | None
    ) -> ResumeVersion:
        await self._lock(resume_id)
        data = data.model_copy(deep=True)
        data.meta.method = "user_edit"
        return await self.versions.create_next(
            resume_id,
            kind="parsed",
            source="user_edit",
            content=data.model_dump(mode="json"),
            change_summary=change_summary or "Edited by user",
        )

    async def add_parsed_version(
        self, resume_id: uuid.UUID, parsed: ParsedResume, summary: str
    ) -> ResumeVersion:
        """New parser output (reparse / Claude enrichment)."""
        resume = await self._lock(resume_id)
        version = await self.versions.create_next(
            resume_id,
            kind="parsed",
            source="parser",
            content=parsed.model_dump(mode="json"),
            change_summary=summary,
        )
        method = "llm_assisted" if parsed.meta.method == "llm_assisted" else "deterministic"
        await self.resumes.update(
            resume,
            {
                "parse_status": "parsed",
                "parse_method": method,
                "parse_error": None,
                "parsed_at": datetime.now(UTC),
            },  # fmt: skip
        )
        return version

    async def create_tailored(
        self, resume_id: uuid.UUID, payload: TailoredVersionCreate
    ) -> ResumeVersion:
        await self._lock(resume_id)
        try:
            async with self.session.begin_nested():
                return await self.versions.create_next(
                    resume_id,
                    kind="tailored",
                    source="tailoring",
                    job_id=payload.job_id,
                    target_role=payload.target_role,
                    target_company=payload.target_company,
                    content=payload.content.model_dump(mode="json"),
                    ats_keywords=payload.ats_keywords,
                    change_summary=payload.change_summary,
                )
        except IntegrityError as exc:
            if "fk_resume_versions_job_id" in str(exc.orig):
                raise NotFoundError("Job not found", {"job_id": str(payload.job_id)}) from exc
            raise

    async def delete(self, resume_id: uuid.UUID) -> tuple[str, uuid.UUID | None]:
        """Delete the row (versions cascade).

        Returns the storage path to remove after the transaction commits, and
        the id of the resume promoted to primary (if the primary was deleted).
        """
        resume = await self.get(resume_id)
        path, was_primary, profile_id = resume.storage_path, resume.is_primary, resume.profile_id
        await self.resumes.delete(resume)
        promoted = None
        if was_primary:
            # Promote the most recent remaining resume.
            remaining = await self.resumes.list_for_profile(profile_id)
            if remaining:
                promoted = (await self.resumes.update(remaining[0], {"is_primary": True})).id
        return path, promoted

    async def delete_file(self, path: str) -> None:
        await self._delete_file_quietly(path)

    # ------------------------------------------------------------ helpers
    async def _lock(self, resume_id: uuid.UUID) -> Resume:
        resume = await self.resumes.lock(resume_id)
        if resume is None:
            raise NotFoundError("Resume not found", {"resume_id": str(resume_id)})
        return resume

    async def _delete_file_quietly(self, path: str) -> None:
        try:
            await self.storage.delete(path)
        except Exception:
            logger.exception("could not delete stored file %s", path)
