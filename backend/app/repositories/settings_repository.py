"""Settings repository: the single `settings` row (id = 1)."""

from sqlalchemy.dialects.postgresql import insert

from app.models.setting import Setting
from app.repositories.base import Repository

SETTINGS_ID = 1


class SettingsRepository(Repository[Setting]):
    model = Setting

    async def get_singleton(self) -> Setting:
        """Return the settings row, recreating it with defaults if it was deleted."""
        row = await self.get(SETTINGS_ID)
        if row is None:
            await self.session.execute(
                insert(Setting).values(id=SETTINGS_ID).on_conflict_do_nothing(index_elements=["id"])
            )
            row = await self.get(SETTINGS_ID)
        if row is None:
            raise RuntimeError("settings row could not be created")
        return row
