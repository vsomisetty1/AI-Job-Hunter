"""Upload validation, sandboxed extraction and antivirus scanning."""

import asyncio
import struct

import pytest

from app.core.exceptions import ServiceUnavailableError
from app.documents.sandbox import ExtractionTimeoutError, extract_document
from app.documents.scanner import ClamdScanner, NoopScanner
from app.documents.validation import (
    FileRejectedError,
    FileTooLargeError,
    UnsupportedFileTypeError,
    sanitize_filename,
    validate_upload,
)
from tests.fixtures import documents as d

MAX = 10 * 1024 * 1024


def check(data: bytes, name: str = "resume.pdf"):
    return validate_upload(data, name, max_bytes=MAX)


# ------------------------------------------------------------- happy paths
def test_valid_pdf_and_docx_accepted():
    pdf = check(d.make_pdf(), "Jordan CV.pdf")
    assert pdf.file_type == "pdf" and pdf.content_type == "application/pdf"
    assert pdf.size_bytes > 0 and len(pdf.sha256) == 64
    docx = check(d.make_docx(), "cv.docx")
    assert docx.file_type == "docx"
    assert docx.content_type.endswith("wordprocessingml.document")


def test_type_comes_from_content_not_name():
    # No extension at all: content decides.
    assert check(d.make_docx(), "resume").file_type == "docx"
    with pytest.raises(FileRejectedError, match="does not match"):
        check(d.make_docx(), "resume.pdf")


# ------------------------------------------------------------- rejections
@pytest.mark.parametrize(
    ("data", "name", "error"),
    [
        (b"", "a.pdf", FileRejectedError),
        (b"hello world", "a.txt", UnsupportedFileTypeError),
        (b"MZ\x90\x00 this is an exe", "a.pdf", UnsupportedFileTypeError),
        (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 100, "a.doc", UnsupportedFileTypeError),
        (b"PK\x03\x04garbage", "a.docx", FileRejectedError),
    ],
)
def test_unsupported_or_corrupt_files(data, name, error):
    with pytest.raises(error):
        check(data, name)


def test_supported_content_with_unsupported_extension():
    with pytest.raises(UnsupportedFileTypeError):
        check(d.make_pdf(), "resume.exe")


def test_too_large():
    with pytest.raises(FileTooLargeError) as exc:
        validate_upload(d.make_pdf(), "a.pdf", max_bytes=100)
    assert exc.value.status_code == 413


def test_truncated_pdf():
    pdf = d.make_pdf()
    with pytest.raises(FileRejectedError, match="truncated"):
        check(pdf[: len(pdf) // 2])


@pytest.mark.parametrize(
    "factory", [d.javascript_pdf, d.hex_escaped_javascript_pdf, d.launch_action_pdf]
)
def test_active_pdf_content_rejected(factory):
    with pytest.raises(FileRejectedError, match="active content") as exc:
        check(factory())
    assert exc.value.details["found"]


@pytest.mark.parametrize(
    ("factory", "match"),
    [
        (d.zip_bomb_docx, "compressed|size"),
        (d.macro_docx, "Macro"),
        (d.remote_template_docx, "remote content"),
        (lambda: d.docx_with_parts({"word/activeX/activeX1.xml": b"<x/>"}), "ActiveX"),
        (lambda: d.docx_with_parts({"word/embeddings/oleObject1.bin": b"x"}), "embedded"),
        (lambda: d.docx_with_parts({"../../evil.sh": b"x"}), "unsafe paths"),
    ],
)
def test_dangerous_docx_rejected(factory, match):
    with pytest.raises(FileRejectedError, match=match):
        check(factory(), "cv.docx")


def test_zip_that_is_not_a_word_document():
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("hello.txt", "hi")
    with pytest.raises(UnsupportedFileTypeError, match="not a Word document"):
        check(buf.getvalue(), "cv.docx")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("../../etc/passwd", "passwd"),
        ("C:\\Users\\me\\My CV.pdf", "My CV.pdf"),
        ("cv\x00\x07.pdf", "cv.pdf"),
        ("  \u202eevil.pdf  ", "evil.pdf"),  # right-to-left override stripped
        ("", "resume.pdf"),
        ("a" * 300 + ".pdf", "a" * 146 + ".pdf"),
    ],
)
def test_sanitize_filename(raw, expected):
    assert sanitize_filename(raw, "pdf") == expected


# --------------------------------------------------------- sandbox
async def _extract(data: bytes, file_type="pdf", **kw):
    opts = {"max_pages": 20, "timeout_seconds": 20, "memory_mb": 1024} | kw
    return await extract_document(file_type, data, **opts)


async def test_sandbox_extracts_pdf_lines_and_links():
    doc = await _extract(d.make_pdf())
    texts = [line.text for line in doc.lines]
    assert texts[0] == "Jordan Rivera"
    assert doc.lines[0].bold and doc.lines[0].size == 18.0
    assert "EXPERIENCE" in texts
    assert "https://www.linkedin.com/in/jordan-rivera" in doc.links
    assert doc.page_count == 1


async def test_sandbox_extracts_docx_including_header():
    doc = await _extract(d.make_docx(contact_in_header=True), "docx")
    assert "jordan.rivera@example.com" in doc.text
    headings = [line.text for line in doc.lines if line.heading_style]
    assert "Experience" in headings and "Jordan Rivera" in headings


async def test_sandbox_rejects_encrypted_pdf():
    with pytest.raises(FileRejectedError, match="password"):
        await _extract(d.make_pdf(encrypt_password="secret"))


async def test_sandbox_catches_javascript_hidden_from_byte_scan():
    data = d.compressed_javascript_pdf()
    check(data)  # passes the raw byte scan: the name is compressed
    with pytest.raises(FileRejectedError, match="active content"):
        await _extract(data)


async def test_sandbox_page_limit():
    blocks = [("text", f"line {i}") for i in range(200)]  # ~5 pages
    with pytest.raises(FileRejectedError, match="pages"):
        await _extract(d.make_pdf(blocks), max_pages=2)


async def test_sandbox_timeout_kills_worker():
    with pytest.raises(ExtractionTimeoutError):
        await _extract(d.make_pdf(), timeout_seconds=0.001)


async def test_sandbox_memory_limit_is_enforced():
    with pytest.raises(FileRejectedError) as exc:
        await _extract(d.make_pdf(), memory_mb=40)
    assert exc.value.details["reason"] in {"too_complex", "unreadable"}


# --------------------------------------------------------- antivirus
async def _fake_clamd(reply: bytes):
    received = bytearray()

    async def handle(reader, writer):
        assert await reader.readuntil(b"\0") == b"zINSTREAM\0"
        while True:
            (size,) = struct.unpack("!L", await reader.readexactly(4))
            if size == 0:
                break
            received.extend(await reader.readexactly(size))
        writer.write(reply)
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    return server, server.sockets[0].getsockname()[1], received


async def test_clamd_clean_and_infected():
    payload = b"x" * 200_000  # several INSTREAM chunks
    server, port, received = await _fake_clamd(b"stream: OK\0")
    async with server:
        result = await ClamdScanner("127.0.0.1", port, 5).scan(payload)
    assert result.clean and bytes(received) == payload

    server, port, _ = await _fake_clamd(b"stream: Eicar-Test-Signature FOUND\0")
    async with server:
        result = await ClamdScanner("127.0.0.1", port, 5).scan(b"X5O!P%@AP")
    assert not result.clean and result.signature == "Eicar-Test-Signature"


async def test_clamd_fails_closed():
    server, port, _ = await _fake_clamd(b"INSTREAM size limit exceeded. ERROR\0")
    async with server:
        with pytest.raises(ServiceUnavailableError):
            await ClamdScanner("127.0.0.1", port, 5).scan(b"data")
    with pytest.raises(ServiceUnavailableError):
        await ClamdScanner("127.0.0.1", 1, 1).scan(b"data")  # nothing listening


async def test_noop_scanner():
    assert (await NoopScanner().scan(b"anything")).clean


def test_docx_external_entities_are_not_resolved():
    """XXE: an entity pointing at a local file must not be expanded."""
    import io
    import socket
    import zipfile

    from app.documents import extract_worker

    src = zipfile.ZipFile(io.BytesIO(d.make_docx()))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as dst:
        for info in src.infolist():
            data = src.read(info.filename)
            if info.filename == "word/document.xml":
                data = data.replace(
                    b"?>", b'?><!DOCTYPE x [<!ENTITY xxe SYSTEM "file:///etc/hostname">]>', 1
                ).replace(b"Jordan Rivera", b"&xxe;", 1)
            dst.writestr(info, data)
    try:
        result = extract_worker._extract_docx(out.getvalue())
    except Exception:  # noqa: BLE001 - rejecting the file is also safe
        return
    assert not any(socket.gethostname() in line["text"] for line in result["lines"])


def test_resource_limits_are_best_effort(monkeypatch):
    """Platforms that reject a limit (macOS RLIMIT_AS, containers) still extract."""
    import resource

    from app.documents import extract_worker

    def refuse(*_args):
        raise ValueError("not allowed")

    monkeypatch.setattr(resource, "setrlimit", refuse)
    assert extract_worker._limit_resources(512, 5) == []
    result = extract_worker._extract_pdf(d.make_pdf(), 20)
    assert result["ok"] and result["lines"]


def test_extract_worker_imports_without_resource_module(monkeypatch):
    """Windows has no `resource` module: the worker must still import and run."""
    import builtins
    import importlib

    import app.documents.extract_worker as worker

    real_import = builtins.__import__

    def no_resource(name, *args, **kwargs):
        if name == "resource":
            raise ImportError("no resource on this platform")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_resource)
    reloaded = importlib.reload(worker)
    assert reloaded._limit_resources(512, 5) == []
    monkeypatch.undo()
    importlib.reload(worker)
