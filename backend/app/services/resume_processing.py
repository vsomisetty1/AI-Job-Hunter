"""Background resume processing: Claude enrichment, reparse, profile generation.

Runs outside the request (BackgroundTaskManager). Database work happens in
short transactions; Claude calls happen between them, never while a
transaction is open.
"""

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, cast

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.agent_0_resume_parser import ResumeParserAgent
from app.agents.agent_1_profile_inference import ProfileInferenceAgent
from app.core.config import Settings
from app.core.exceptions import NotFoundError
from app.documents.sandbox import ExtractedDocument, extract_document
from app.documents.scanner import NoopScanner
from app.documents.validation import FileType
from app.repositories.candidate_profile_repository import CandidateProfileRepository
from app.repositories.resume_repository import ResumeRepository, ResumeVersionRepository
from app.schemas.parsed_resume import ParsedResume
from app.services.profile_service import ProfileService
from app.services.resume_service import ResumeService
from app.storage import StorageBackend

logger = logging.getLogger(__name__)

PROFILE_TASK_KEY = "profile-generation"


@dataclass
class ResumeProcessor:
    settings: Settings
    storage: StorageBackend
    parser: ResumeParserAgent
    profiler: ProfileInferenceAgent
    sessionmaker: async_sessionmaker[AsyncSession]
    # One profile build at a time: a manual "regenerate" and an upload-triggered
    # build must not interleave their writes.
    _profile_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)
    # Called after a profile build is saved (bootstrap: re-filter and re-score
    # jobs for the new profile). Its failure never fails the build.
    after_profile: Callable[[], Awaitable[Any]] | None = field(default=None, repr=False)

    def _resume_service(self, session: AsyncSession) -> ResumeService:
        return ResumeService(
            session, settings=self.settings, storage=self.storage, scanner=NoopScanner(),
            parser=self.parser,
        )  # fmt: skip

    async def _extract(self, resume_id: uuid.UUID) -> ExtractedDocument:
        async with self.sessionmaker() as session:
            resume = await ResumeRepository(session).get(resume_id)
            if resume is None:
                raise NotFoundError("Resume not found", {"resume_id": str(resume_id)})
            path, file_type = resume.storage_path, cast(FileType, resume.file_type)
        data = await self.storage.get(path)
        return await extract_document(
            file_type,
            data,
            max_pages=self.settings.max_pdf_pages,
            timeout_seconds=self.settings.parse_timeout_seconds,
            memory_mb=self.settings.parse_memory_limit_mb,
        )

    async def reparse(self, resume_id: uuid.UUID, *, use_llm: bool) -> dict[str, Any]:
        doc = await self._extract(resume_id)
        parsed = await self.parser.run(doc, use_llm=use_llm, resume_id=resume_id)
        async with self.sessionmaker() as session, session.begin():
            version = await self._resume_service(session).add_parsed_version(
                resume_id,
                parsed,
                "Re-parsed"
                + (" with AI assistance" if parsed.meta.method == "llm_assisted" else ""),
            )
        return {"resume_id": str(resume_id), "version_id": str(version.id),
                "method": parsed.meta.method, "confidence": parsed.meta.confidence}  # fmt: skip

    async def enrich_and_profile(self, resume_id: uuid.UUID) -> dict[str, Any]:
        """After an upload: improve weak sections with Claude, then build the profile."""
        result: dict[str, Any] = {"resume_id": str(resume_id)}
        async with self.sessionmaker() as session:
            latest = await ResumeVersionRepository(session).latest(resume_id, "parsed")
            parsed = ParsedResume.model_validate(latest.content) if latest else None
            resume = await ResumeRepository(session).get(resume_id)
            is_primary = bool(resume and resume.is_primary)
        if parsed is None:
            raise NotFoundError("Resume not found", {"resume_id": str(resume_id)})

        if self.parser.llm.enabled and parsed.meta.method == "deterministic":
            doc = await self._extract(resume_id)
            enriched = await self.parser.run(doc, use_llm=True, resume_id=resume_id)
            if enriched.meta.method == "llm_assisted":
                async with self.sessionmaker() as session, session.begin():
                    await self._resume_service(session).add_parsed_version(
                        resume_id, enriched, "AI-assisted parse of hard-to-read sections"
                    )
                result["enriched_sections"] = enriched.meta.llm_sections
        if is_primary:
            result["profile"] = await self.generate_profile(resume_id=resume_id)
        return result

    async def generate_profile(
        self,
        *,
        resume_id: uuid.UUID | None = None,
        keep_overrides: bool = True,
        use_llm: bool = True,
    ) -> dict[str, Any]:
        async with self._profile_lock:
            result = await self._generate_profile(
                resume_id=resume_id, keep_overrides=keep_overrides, use_llm=use_llm
            )
        if self.after_profile is not None:
            try:
                await self.after_profile()
                result["jobs_rescored"] = True
            except Exception:
                logger.exception("re-scoring after the profile build failed")
                result["jobs_rescored"] = False
        return result

    async def _generate_profile(
        self, *, resume_id: uuid.UUID | None, keep_overrides: bool, use_llm: bool
    ) -> dict[str, Any]:
        async with self.sessionmaker() as session, session.begin():
            profile = await CandidateProfileRepository(session).get_active()
            if profile is None:
                raise NotFoundError("No profile yet: upload a resume first.")
            resumes = ResumeRepository(session)
            resume = (
                await resumes.get(resume_id) if resume_id else await resumes.get_primary(profile.id)
            )
            if resume is None or resume.profile_id != profile.id:
                raise NotFoundError("No resume to build the profile from.")
            version = await ResumeVersionRepository(session).latest(resume.id, "parsed")
            if version is None:
                raise NotFoundError("The resume has no parsed data yet.")
            parsed = ParsedResume.model_validate(version.content)
            version_id, rid, profile_id = version.id, resume.id, profile.id
            await ProfileService(session).mark("running")

        try:
            build = await self.profiler.run(parsed, use_llm=use_llm, profile_id=profile_id)
        except Exception as exc:
            async with self.sessionmaker() as session, session.begin():
                await ProfileService(session).mark("failed", f"{type(exc).__name__}: {exc}"[:1000])
            raise

        async with self.sessionmaker() as session, session.begin():
            await ProfileService(session).apply_build(
                build,
                keep_overrides=keep_overrides,
                source_resume_id=str(rid),
                source_version_id=str(version_id),
            )
        return {"source": build.inference.source, "llm_errors": build.llm_errors,
                "resume_id": str(rid)}  # fmt: skip
