import os
import stat

import httpx
import pytest
import respx

from app.storage.base import StorageError, StorageNotFoundError
from app.storage.local_storage import LocalStorage
from app.storage.supabase_storage import SupabaseStorage


async def test_local_roundtrip_and_permissions(tmp_path):
    store = LocalStorage(tmp_path)
    await store.put("resumes/p1/abc.pdf", b"%PDF-data", "application/pdf")
    assert await store.get("resumes/p1/abc.pdf") == b"%PDF-data"
    mode = stat.S_IMODE(os.stat(tmp_path / "resumes/p1/abc.pdf").st_mode)
    assert mode == 0o600
    assert not [p for p in (tmp_path / "resumes/p1").iterdir() if p.name.startswith(".upload-")]
    await store.delete("resumes/p1/abc.pdf")
    await store.delete("resumes/p1/abc.pdf")  # idempotent
    with pytest.raises(StorageNotFoundError):
        await store.get("resumes/p1/abc.pdf")


@pytest.mark.parametrize(
    "path", ["../outside.pdf", "/etc/passwd", "resumes/../../x", "a\\b.pdf", "a//b", ""]
)
async def test_local_rejects_unsafe_paths(tmp_path, path):
    with pytest.raises(ValueError, match="unsafe"):
        await LocalStorage(tmp_path).put(path, b"x", "text/plain")


async def test_local_write_failure_is_storage_error_and_leaves_no_temp(tmp_path, monkeypatch):
    def disk_full(*_args):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(os, "replace", disk_full)
    with pytest.raises(StorageError):
        await LocalStorage(tmp_path).put("a/b.pdf", b"x", "application/pdf")
    assert not list((tmp_path / "a").iterdir())  # temp file cleaned up


SUPA = "https://proj.supabase.test"


@respx.mock(assert_all_called=False)
async def test_supabase_put_get_delete(respx_mock):
    store = SupabaseStorage(SUPA, "service-key", "job-hunter")
    obj = f"{SUPA}/storage/v1/object/job-hunter/resumes/p1/abc.pdf"
    upload = respx_mock.post(obj).mock(return_value=httpx.Response(200, json={"Key": "k"}))
    download = respx_mock.get(obj).mock(return_value=httpx.Response(200, content=b"%PDF"))
    remove = respx_mock.delete(f"{SUPA}/storage/v1/object/job-hunter").mock(
        return_value=httpx.Response(200, json=[])
    )

    await store.put("resumes/p1/abc.pdf", b"%PDF", "application/pdf")
    req = upload.calls.last.request
    assert req.headers["authorization"] == "Bearer service-key"
    # storage3 sends multipart; the file part carries the content type.
    assert b"application/pdf" in req.content and b"%PDF" in req.content
    assert req.headers["x-upsert"] == "false"
    assert await store.get("resumes/p1/abc.pdf") == b"%PDF"
    assert download.called
    await store.delete("resumes/p1/abc.pdf")
    assert remove.called


@respx.mock
async def test_supabase_errors_mapped(respx_mock):
    store = SupabaseStorage(SUPA, "k", "job-hunter")
    obj = f"{SUPA}/storage/v1/object/job-hunter/resumes/x.pdf"
    respx_mock.get(obj).mock(
        return_value=httpx.Response(
            400, json={"statusCode": "404", "error": "not_found", "message": "Object not found"}
        )
    )
    respx_mock.post(obj).mock(side_effect=httpx.ConnectError("down"))
    with pytest.raises(StorageNotFoundError):
        await store.get("resumes/x.pdf")
    with pytest.raises(StorageError):
        await store.put("resumes/x.pdf", b"x", "application/pdf")
