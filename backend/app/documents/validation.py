"""Upload validation: decide whether a file is a safe PDF or DOCX resume.

Defence in depth for untrusted uploads (nothing here executes file content):

1. Size limits and an exact type check from the file's bytes (magic numbers),
   cross-checked against the file extension. The browser's MIME type is
   advisory only.
2. Structural checks that reject active or dangerous content a resume never
   needs: PDF JavaScript / launch actions / embedded files / XFA forms;
   DOCX macros, ActiveX, embedded OLE objects, remote templates and zip bombs.
3. Optional antivirus scan (ClamAV, app/documents/scanner.py).
4. Text extraction runs in a separate, resource-limited, killable process
   (app/documents/sandbox.py), which also inspects the PDF catalog properly.

Files are stored under generated names and served only as attachments.
"""

import io
import re
import unicodedata
import zipfile
from dataclasses import dataclass, field
from pathlib import PurePosixPath, PureWindowsPath
from typing import Literal

from fastapi import status

from app.core.exceptions import AppError
from app.utils.hashing import hash_file

FileType = Literal["pdf", "docx"]

CONTENT_TYPES: dict[FileType, str] = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
EXTENSIONS: dict[str, FileType] = {".pdf": "pdf", ".docx": "docx"}

# DOCX (zip) limits: generous for real resumes, fatal for zip bombs.
MAX_ZIP_ENTRIES = 1000
MAX_ZIP_UNCOMPRESSED_BYTES = 100 * 1024 * 1024
MAX_ZIP_ENTRY_RATIO = 200  # uncompressed / compressed, per entry

# PDF name tokens for active content. Matched on raw bytes, including the
# "#xx" hex-escaped spellings (e.g. /J#61vaScript) attackers use to hide them.
_PDF_DANGEROUS_NAMES = ("JavaScript", "JS", "Launch", "EmbeddedFile", "EmbeddedFiles", "XFA")

# Relationship types that load remote content when Word opens the file.
_EXTERNAL_REL = re.compile(
    rb"<Relationship\b[^>]*(?:attachedTemplate|/frame\"|oleObject|subDocument)[^>]*"
    rb"TargetMode=\"External\"|<Relationship\b[^>]*TargetMode=\"External\"[^>]*"
    rb"(?:attachedTemplate|/frame\"|oleObject|subDocument)"
)

_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"  # legacy .doc / encrypted Office


class FileRejectedError(AppError):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "invalid_file"


class UnsupportedFileTypeError(AppError):
    status_code = status.HTTP_415_UNSUPPORTED_MEDIA_TYPE
    code = "unsupported_file_type"


class FileTooLargeError(AppError):
    status_code = status.HTTP_413_CONTENT_TOO_LARGE
    code = "file_too_large"


@dataclass(frozen=True)
class ValidatedFile:
    file_type: FileType
    filename: str  # sanitised, for display only
    size_bytes: int
    sha256: str
    content_type: str
    warnings: list[str] = field(default_factory=list)


def sanitize_filename(name: str | None, file_type: FileType | None = None) -> str:
    """Display-safe base name: no path parts, control characters or odd Unicode."""
    raw = name or ""
    # Strip both POSIX and Windows path components.
    raw = PureWindowsPath(PurePosixPath(raw).name).name
    raw = unicodedata.normalize("NFKC", raw)
    raw = "".join(c for c in raw if unicodedata.category(c)[0] != "C")  # control/format chars
    raw = re.sub(r"\s+", " ", raw).strip().strip(".")
    if len(raw) > 150:
        stem, dot, ext = raw.rpartition(".")
        raw = (stem[: 150 - len(ext) - 1] + dot + ext) if dot and len(ext) <= 5 else raw[:150]
    if not raw:
        raw = f"resume.{file_type}" if file_type else "resume"
    return raw


def detect_file_type(data: bytes) -> FileType:
    if data[:1024].lstrip(b"\x00\t\n\r\x0c ").startswith(b"%PDF-"):
        return "pdf"
    if data.startswith(b"PK\x03\x04"):
        return "docx"
    if data.startswith(_OLE_MAGIC):
        raise UnsupportedFileTypeError(
            "Legacy .doc files and password-protected Word files are not supported. "
            "Save the resume as .docx (without a password) or PDF."
        )
    raise UnsupportedFileTypeError("Only PDF and DOCX resumes are supported.")


def _pdf_name_pattern(name: str) -> re.Pattern[bytes]:
    # Each character may appear literally or as #xx; names end at a delimiter.
    parts = []
    for ch in name:
        hexcode = f"{ord(ch):02x}"
        parts.append(f"(?:{re.escape(ch)}|#(?i:{hexcode}))")
    return re.compile(rb"/" + "".join(parts).encode() + rb"(?![A-Za-z0-9#])")


_PDF_PATTERNS = {n: _pdf_name_pattern(n) for n in _PDF_DANGEROUS_NAMES}


def check_pdf(data: bytes) -> list[str]:
    tail = data[-4096:]
    if b"%%EOF" not in tail:
        raise FileRejectedError("The PDF appears truncated or corrupted.")
    found = sorted(n for n, pat in _PDF_PATTERNS.items() if pat.search(data))
    if found:
        raise FileRejectedError(
            "The PDF contains active content (JavaScript, launch actions, embedded files "
            "or forms) and was rejected for safety. Export or print it to a plain PDF "
            "and upload again.",
            {"found": found},
        )
    return []


def check_docx(data: bytes) -> list[str]:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise FileRejectedError("The DOCX file is corrupted.") from exc

    with zf:
        infos = zf.infolist()
        if len(infos) > MAX_ZIP_ENTRIES:
            raise FileRejectedError("The DOCX file has too many parts.")
        total = 0
        names: dict[str, str] = {}  # lower-case name -> real name
        for info in infos:
            name = info.filename
            if name.startswith(("/", "\\")) or ".." in PurePosixPath(name).parts:
                raise FileRejectedError("The DOCX file contains unsafe paths.")
            if info.flag_bits & 0x1:
                raise FileRejectedError("Encrypted DOCX parts are not supported.")
            total += info.file_size
            if total > MAX_ZIP_UNCOMPRESSED_BYTES:
                raise FileRejectedError("The DOCX file expands to an unsafe size.")
            if info.compress_size and info.file_size / info.compress_size > MAX_ZIP_ENTRY_RATIO:
                raise FileRejectedError("The DOCX file is abnormally compressed.")
            names[name.lower()] = name

        if "[content_types].xml" not in names or "word/document.xml" not in names:
            raise UnsupportedFileTypeError("The file is a ZIP archive but not a Word document.")

        content_types = zf.read("[Content_Types].xml")
        if b"macroEnabled" in content_types or any(n.endswith("vbaproject.bin") for n in names):
            raise FileRejectedError(
                "Macro-enabled Word files are not accepted. Save as a regular .docx."
            )
        if any(n.startswith("word/activex/") for n in names):
            raise FileRejectedError("Word files with ActiveX controls are not accepted.")
        if any(
            n.startswith("word/embeddings/") and n.endswith((".bin", ".exe", ".dll", ".js"))
            for n in names
        ):
            raise FileRejectedError("Word files with embedded objects are not accepted.")

        # Remote templates / frames are a known injection vector.
        for lower, real in names.items():
            if lower.endswith(".rels"):
                rels = zf.read(real)
                if _EXTERNAL_REL.search(rels):
                    raise FileRejectedError(
                        "The Word file references remote content and was rejected for safety."
                    )
    return []


def validate_upload(data: bytes, filename: str | None, *, max_bytes: int) -> ValidatedFile:
    size = len(data)
    if size == 0:
        raise FileRejectedError("The file is empty.")
    if size > max_bytes:
        raise FileTooLargeError(
            f"The file is larger than {max_bytes // (1024 * 1024)} MB.",
            {"max_bytes": max_bytes, "size_bytes": size},
        )

    file_type = detect_file_type(data)
    ext = PurePosixPath((filename or "").lower()).suffix
    if ext and ext in EXTENSIONS and EXTENSIONS[ext] != file_type:
        raise FileRejectedError(
            f"The file extension does not match its content (content is {file_type.upper()})."
        )
    if ext and ext not in EXTENSIONS:
        raise UnsupportedFileTypeError("Only .pdf and .docx files are supported.")

    warnings = check_pdf(data) if file_type == "pdf" else check_docx(data)
    return ValidatedFile(
        file_type=file_type,
        filename=sanitize_filename(filename, file_type),
        size_bytes=size,
        sha256=hash_file(data),
        content_type=CONTENT_TYPES[file_type],
        warnings=warnings,
    )
