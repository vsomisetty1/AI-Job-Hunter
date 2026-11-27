"""Local filesystem storage (default; good for a single-machine install)."""

import asyncio
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from app.storage.base import StorageError, StorageNotFoundError, StoredFile, check_path


class LocalStorage:
    name = "local"

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()

    def _resolve(self, path: str) -> Path:
        full = (self.root / check_path(path)).resolve()
        if not full.is_relative_to(self.root):
            raise ValueError(f"unsafe storage path: {path!r}")
        return full

    def _put(self, path: str, data: bytes) -> None:
        target = self._resolve(path)
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Atomic write: never leave a half-written file behind.
        fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=".upload-")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            os.chmod(tmp, 0o600)
            os.replace(tmp, target)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    async def put(self, path: str, data: bytes, content_type: str) -> None:
        try:
            await asyncio.to_thread(self._put, path, data)
        except OSError as exc:
            raise StorageError("Could not save the file.") from exc

    async def get(self, path: str) -> bytes:
        target = self._resolve(path)
        try:
            return await asyncio.to_thread(target.read_bytes)
        except FileNotFoundError as exc:
            raise StorageNotFoundError("Stored file not found.") from exc
        except OSError as exc:
            raise StorageError("Could not read the file.") from exc

    async def delete(self, path: str) -> None:
        target = self._resolve(path)
        await asyncio.to_thread(target.unlink, True)

    def _list(self, prefix: str) -> list[StoredFile]:
        base = self._resolve(prefix)
        if not base.is_dir():
            return []
        out = []
        for f in base.rglob("*"):
            if f.is_file() and not f.name.startswith(".upload-"):  # skip half-written temp files
                st = f.stat()
                modified = datetime.fromtimestamp(st.st_mtime, UTC)
                out.append(StoredFile(f.relative_to(self.root).as_posix(), st.st_size, modified))
        return sorted(out, key=lambda x: x.path)

    async def list_files(self, prefix: str) -> list[StoredFile]:
        return await asyncio.to_thread(self._list, prefix)
