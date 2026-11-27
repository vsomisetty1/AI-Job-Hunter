"""Supabase Storage backend (private bucket, service-role key, server-side only)."""

import logging

import httpx
from storage3 import AsyncStorageClient
from storage3._async.file_api import AsyncBucketProxy
from storage3.exceptions import StorageApiError

from app.storage.base import StorageError, StorageNotFoundError, check_path

logger = logging.getLogger(__name__)


class SupabaseStorage:
    name = "supabase"

    def __init__(self, url: str, service_role_key: str, bucket: str, timeout: int = 30) -> None:
        self.bucket = bucket
        headers = {"apikey": service_role_key, "Authorization": f"Bearer {service_role_key}"}
        self._client = AsyncStorageClient(
            f"{url.rstrip('/')}/storage/v1/",
            headers,
            http_client=httpx.AsyncClient(headers=headers, timeout=timeout, follow_redirects=False),
        )

    def _bucket(self) -> AsyncBucketProxy:
        return self._client.from_(self.bucket)

    async def put(self, path: str, data: bytes, content_type: str) -> None:
        try:
            await self._bucket().upload(
                check_path(path),
                data,
                {"content-type": content_type, "upsert": "false", "cache-control": "no-store"},
            )
        except StorageApiError as exc:
            logger.error("supabase upload failed: %s", exc)
            raise StorageError("Could not save the file to storage.") from exc
        except Exception as exc:  # network errors from the HTTP client
            logger.error("supabase upload failed: %s", exc)
            raise StorageError("Could not reach file storage.") from exc

    async def get(self, path: str) -> bytes:
        try:
            return bytes(await self._bucket().download(check_path(path)))
        except StorageApiError as exc:
            if str(getattr(exc, "status", "")) in {"400", "404"}:
                raise StorageNotFoundError("Stored file not found.") from exc
            raise StorageError("Could not read the file from storage.") from exc
        except Exception as exc:
            raise StorageError("Could not reach file storage.") from exc

    async def delete(self, path: str) -> None:
        try:
            await self._bucket().remove([check_path(path)])
        except Exception as exc:
            raise StorageError("Could not delete the file from storage.") from exc
