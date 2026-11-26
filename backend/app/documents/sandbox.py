"""Run document text extraction in an isolated, killable child process.

Why: PDF/DOCX parsers are complex C/Python code fed untrusted input. A
malformed or hostile file can hang the parser, exhaust memory, or (worst
case) exploit a parser bug. The child process gets an address-space and CPU
limit, no core dumps, few file descriptors, and is killed on timeout, so
none of that can take the API process down with it.
"""

import asyncio
import logging
import multiprocessing as mp
from dataclasses import dataclass, field
from typing import Any

from fastapi import status

from app.core.exceptions import AppError
from app.documents import extract_worker
from app.documents.validation import FileRejectedError, FileType

logger = logging.getLogger(__name__)

# forkserver: children fork from a small, clean server process, not from the
# API process (no inherited sockets, threads or database connections).
_CTX = mp.get_context("forkserver")
# Load the parsers once in the fork server so each extraction starts fast.
_CTX.set_forkserver_preload(["app.documents.extract_worker", "pdfplumber", "docx"])


class ExtractionTimeoutError(AppError):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "parse_timeout"


@dataclass
class ExtractedLine:
    text: str
    bold: bool = False
    size: float = 0.0
    heading_style: bool = False


@dataclass
class ExtractedDocument:
    file_type: FileType
    page_count: int
    lines: list[ExtractedLine]
    links: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(line.text for line in self.lines)


_ERROR_MESSAGES = {
    "encrypted": "The PDF is password-protected. Upload a version without a password.",
    "too_complex": "The file is too large or complex to read safely.",
    "unreadable": "The file could not be read. It may be corrupted.",
}


def _run_blocking(
    file_type: FileType, data: bytes, options: dict[str, Any], timeout: float
) -> dict[str, Any]:
    parent_conn, child_conn = _CTX.Pipe(duplex=False)
    proc = _CTX.Process(
        target=extract_worker.child_main,
        args=(child_conn, file_type, data, options),
        daemon=True,
    )
    proc.start()
    child_conn.close()
    try:
        if not parent_conn.poll(timeout):
            raise ExtractionTimeoutError("Reading the file took too long.")
        try:
            return parent_conn.recv()
        except EOFError:
            # Child died without answering (killed by a resource limit, crashed).
            return {"ok": False, "error": "too_complex", "message": "worker exited"}
    finally:
        parent_conn.close()
        if proc.is_alive():
            proc.kill()
        proc.join(timeout=5)


async def extract_document(
    file_type: FileType,
    data: bytes,
    *,
    max_pages: int,
    timeout_seconds: float,
    memory_mb: int,
) -> ExtractedDocument:
    options = {
        "max_pages": max_pages,
        "memory_mb": memory_mb,
        "cpu_seconds": max(1, int(timeout_seconds)),
    }
    result = await asyncio.to_thread(_run_blocking, file_type, data, options, timeout_seconds)

    if not result.get("ok"):
        error = result.get("error", "unreadable")
        if error == "unreadable":
            logger.warning("extraction failed: %s", result.get("message"))
        message = (
            result.get("message")
            if error == "too_many_pages"
            else _ERROR_MESSAGES.get(error, _ERROR_MESSAGES["unreadable"])
        )
        raise FileRejectedError(message, {"reason": error})

    if result["findings"]:
        raise FileRejectedError(
            "The PDF contains active content (JavaScript, actions, embedded files or forms) "
            "and was rejected for safety. Export or print it to a plain PDF and upload again.",
            {"found": result["findings"]},
        )

    return ExtractedDocument(
        file_type=file_type,
        page_count=result["page_count"],
        lines=[ExtractedLine(**line) for line in result["lines"]],
        links=list(dict.fromkeys(result["links"])),
    )
