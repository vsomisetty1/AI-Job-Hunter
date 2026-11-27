"""Tracked companies (job boards): add, verify, update, remove, suggestions."""

import uuid
from typing import Any

from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.base import Connector
from app.connectors.company_directory import DIRECTORY
from app.connectors.http import BoardNotFoundError, ConnectorError
from app.core.exceptions import AppError, ConflictError, DomainValidationError
from app.models.company import Company
from app.repositories.company_repository import CompanyRepository
from app.schemas.job import CompanyCreate, CompanyUpdate


class BoardUnavailableError(AppError):
    status_code = status.HTTP_502_BAD_GATEWAY
    code = "board_unavailable"


class CompanyService:
    def __init__(self, session: AsyncSession, connectors: dict[str, Connector]) -> None:
        self.session = session
        self.connectors = connectors
        self.repo = CompanyRepository(session)

    async def list_companies(self) -> list[tuple[Company, int]]:
        return await self.repo.list_with_counts()

    async def get(self, company_id: uuid.UUID) -> Company:
        return await self.repo.get_or_404(company_id)

    async def add(self, body: CompanyCreate) -> Company:
        slug = body.slug.strip().lower()
        if await self.repo.get_by_board(body.source, slug):
            raise ConflictError(
                "This board is already tracked.", {"source": body.source, "slug": slug}
            )
        connector = self.connectors[body.source]
        try:
            info = await connector.board_info(slug)
        except BoardNotFoundError as exc:
            raise DomainValidationError(
                f"No {connector.display_name} job board named '{slug}'. Check the name in the "
                f"board's URL, e.g. {connector.careers_url('company-name')}.",
                {"source": body.source, "slug": slug},
            ) from exc
        except ConnectorError as exc:
            raise BoardUnavailableError(
                f"Could not reach {connector.display_name}: {exc}. Try again later."
            ) from exc
        return await self.repo.add(
            Company(
                name=(body.name or info.name).strip(),
                source=body.source,
                slug=slug,
                careers_url=info.careers_url,
            )
        )

    async def add_suggested(self, keys: list[tuple[str, str]]) -> list[Company]:
        """Add directory suggestions by (source, slug); already tracked ones are skipped.

        Suggestions were verified when the directory was written, so they are
        not re-checked here; a board that moved shows up as "not found" on crawl.
        """
        known = {(e.source, e.slug): e for e in DIRECTORY}
        added = []
        for key in keys:
            entry = known.get(key)
            if entry is None:
                raise DomainValidationError(
                    "Not a suggested board.", {"source": key[0], "slug": key[1]}
                )
            if await self.repo.get_by_board(entry.source, entry.slug):
                continue
            connector = self.connectors[entry.source]
            added.append(
                await self.repo.add(
                    Company(
                        name=entry.name,
                        source=entry.source,
                        slug=entry.slug,
                        careers_url=connector.careers_url(entry.slug),
                    )  # fmt: skip
                )
            )
        return added

    async def update(self, company_id: uuid.UUID, body: CompanyUpdate) -> Company:
        company = await self.repo.get_or_404(company_id)
        changes = body.model_dump(exclude_unset=True, exclude_none=True)
        return await self.repo.update(company, changes) if changes else company

    async def delete(self, company_id: uuid.UUID) -> None:
        company = await self.repo.get_or_404(company_id)
        if await self.repo.has_jobs(company_id):
            raise ConflictError(
                "This company has discovered jobs; stop tracking it instead of deleting it.",
                {"company_id": str(company_id)},
            )
        await self.repo.delete(company)

    async def directory(self) -> list[dict[str, Any]]:
        tracked = {(c.source, c.slug) for c, _ in await self.repo.list_with_counts()}
        return [
            {
                "source": e.source,
                "slug": e.slug,
                "name": e.name,
                "added": (e.source, e.slug) in tracked,
            }
            for e in DIRECTORY
        ]
