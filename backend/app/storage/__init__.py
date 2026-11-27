"""File storage backends."""

from app.core.config import Settings
from app.storage.base import StorageBackend, StorageError, StorageNotFoundError
from app.storage.local_storage import LocalStorage


def build_storage(settings: Settings) -> StorageBackend:
    if settings.storage_backend == "supabase":
        from app.storage.supabase_storage import SupabaseStorage

        if not (settings.supabase_url and settings.supabase_service_role_key):
            raise ValueError("Supabase storage needs SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY")
        return SupabaseStorage(
            settings.supabase_url,
            settings.supabase_service_role_key.get_secret_value(),
            settings.supabase_bucket,
        )
    return LocalStorage(settings.local_storage_dir)


__all__ = [
    "LocalStorage",
    "StorageBackend",
    "StorageError",
    "StorageNotFoundError",
    "build_storage",
]
