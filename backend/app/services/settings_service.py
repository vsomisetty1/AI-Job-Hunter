"""Settings service: business rules for user preferences."""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import DomainValidationError
from app.models.setting import Setting
from app.repositories.settings_repository import SettingsRepository
from app.schemas.settings import SettingsUpdate

logger = logging.getLogger(__name__)


class SettingsService:
    def __init__(self, session: AsyncSession) -> None:
        self.repo = SettingsRepository(session)

    async def get(self) -> Setting:
        return await self.repo.get_singleton()

    async def update(self, patch: SettingsUpdate) -> Setting:
        current = await self.repo.get_singleton()
        changes = patch.changes()
        if not changes:
            return current

        # Cross-field rule checked against the merged result, so a PATCH that
        # sends only one salary field is still validated against the other.
        salary_min = changes.get("salary_min", current.salary_min)
        salary_target = changes.get("salary_target", current.salary_target)
        if salary_min is not None and salary_target is not None and salary_min > salary_target:
            raise DomainValidationError(
                "salary_min must be <= salary_target",
                {"salary_min": salary_min, "salary_target": salary_target},
            )

        updated = await self.repo.update(current, changes)
        logger.info("settings updated", extra={"fields": sorted(changes)})
        return updated
