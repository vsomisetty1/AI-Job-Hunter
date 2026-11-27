"""Text extraction that runs INSIDE the sandbox process (see sandbox.py).

Keep this module light: it is imported in a fresh child process, so it must
not import the app (database, settings, ...). It returns plain dicts.

Output shape (all keys always present):
    {
      "ok": True,
      "page_count": int,
      "lines": [{"text": str, "bold": bool, "size": float, "heading_style": bool}],
      "links": [str],              # external hyperlink targets
      "findings": [str],           # security findings (reject if non-empty)
    }
or {"ok": False, "error": "<code>", "message": str}
"""

from __future__ import annotations

import io
import statistics
import sys
import traceback
from typing import Any

_MAX_LINES = 5000


def _limit_resources(memory_mb: int, cpu_seconds: int) -> list[str]:
    """Apply OS resource limits where the platform supports them.

    Linux enforces all of them. macOS does not enforce RLIMIT_AS (and may
    reject it); Windows has no `resource` module. The parent's hard timeout
    and kill apply everywhere, so isolation never depends on these.
    Returns the limits that were applied.
    """
    try:
        import resource
    except ImportError:  # Windows
        return []
    mem = memory_mb * 1024 * 1024
    wanted = [
        ("cpu", resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds + 1)),
        ("core", resource.RLIMIT_CORE, (0, 0)),
        ("nofile", resource.RLIMIT_NOFILE, (64, 64)),
    ]
    if sys.platform.startswith("linux"):
        wanted.insert(0, ("memory", resource.RLIMIT_AS, (mem, mem)))
    applied = []
    for name, limit, value in wanted:
        try:
            resource.setrlimit(limit, value)
            applied.append(name)
        except ValueError, OSError:  # not permitted / not supported here
            pass
    return applied


# --------------------------------------------------------------------- PDF
def _pdf_findings(pdf: Any) -> list[str]:
    """Inspect the resolved PDF catalog (catches names hidden in object streams)."""
    from pdfminer.pdftypes import resolve1

    findings: list[str] = []
    catalog = resolve1(pdf.doc.catalog) or {}

    def name_of(obj: Any) -> str:
        obj = resolve1(obj)
        return getattr(obj, "name", str(obj))

    open_action = resolve1(catalog.get("OpenAction"))
    if isinstance(open_action, dict) and name_of(open_action.get("S")) in {
        "JavaScript",
        "Launch",
        "ImportData",
        "SubmitForm",
    }:
        findings.append("open_action")
    if resolve1(catalog.get("AA")):
        findings.append("document_actions")
    names = resolve1(catalog.get("Names")) or {}
    if isinstance(names, dict):
        if resolve1(names.get("JavaScript")):
            findings.append("javascript")
        if resolve1(names.get("EmbeddedFiles")):
            findings.append("embedded_files")
    acroform = resolve1(catalog.get("AcroForm")) or {}
    if isinstance(acroform, dict) and resolve1(acroform.get("XFA")):
        findings.append("xfa_form")

    for page in pdf.pages:
        for annot in page.annots or []:
            data = annot.get("data") or {}
            action = resolve1(data.get("A"))
            if isinstance(action, dict) and name_of(action.get("S")) in {"JavaScript", "Launch"}:
                findings.append("annotation_action")
                return sorted(set(findings))
    return sorted(set(findings))


def _extract_pdf(data: bytes, max_pages: int) -> dict[str, Any]:
    import pdfplumber

    try:
        pdf = pdfplumber.open(io.BytesIO(data))
    except Exception as exc:
        # pdfplumber wraps pdfminer errors; look through the chain.
        chain = [exc, *exc.args, exc.__cause__]
        if any("PDFPasswordIncorrect" in type(e).__name__ for e in chain if e is not None):
            return {"ok": False, "error": "encrypted", "message": "The PDF is password-protected."}
        raise

    with pdf:
        if len(pdf.pages) > max_pages:
            return {
                "ok": False,
                "error": "too_many_pages",
                "message": f"The PDF has {len(pdf.pages)} pages (limit {max_pages}).",
            }
        findings = _pdf_findings(pdf)
        if findings:
            return {"ok": True, "page_count": len(pdf.pages), "lines": [], "links": [],
                    "findings": findings}  # fmt: skip

        raw_lines: list[dict[str, Any]] = []
        links: list[str] = []
        for page in pdf.pages:
            for link in page.hyperlinks or []:
                uri = link.get("uri")
                if isinstance(uri, bytes):
                    uri = uri.decode("utf-8", "ignore")
                if uri:
                    links.append(str(uri))
            for line in page.extract_text_lines(layout=False, strip=True, return_chars=True):
                text = line.get("text", "")
                chars = line.get("chars") or []
                if not text:
                    continue
                sizes = [c.get("size", 0.0) for c in chars if c.get("text", "").strip()]
                fonts = [str(c.get("fontname", "")) for c in chars if c.get("text", "").strip()]
                bold = bool(fonts) and sum("bold" in f.lower() for f in fonts) / len(fonts) > 0.6
                raw_lines.append(
                    {
                        "text": text,
                        "bold": bold,
                        "size": round(statistics.median(sizes), 2) if sizes else 0.0,
                        "heading_style": False,
                    }
                )
                if len(raw_lines) >= _MAX_LINES:
                    break
        return {
            "ok": True,
            "page_count": len(pdf.pages),
            "lines": raw_lines,
            "links": links,
            "findings": [],
        }


# -------------------------------------------------------------------- DOCX
def _docx_paragraph(p: Any) -> dict[str, Any] | None:
    text = p.text.strip()
    if not text:
        return None
    style = (p.style.name if p.style is not None else "") or ""
    # Word bullets come from list styles / numbering, not from a character.
    ppr = p._p.pPr
    if "list" in style.lower() or (ppr is not None and ppr.numPr is not None):
        text = "\u2022 " + text
    runs = [r for r in p.runs if r.text.strip()]
    bold = bool(runs) and all(bool(r.bold) for r in runs)
    sizes = [r.font.size.pt for r in runs if r.font.size is not None]
    return {
        "text": text,
        "bold": bold,
        "size": round(statistics.median(sizes), 2) if sizes else 0.0,
        "heading_style": style.lower().startswith(("heading", "title")),
    }


def _docx_table_lines(table: Any) -> list[dict[str, Any]]:
    """Lines of a body table, row by row.

    Resumes often lay out a role as one row: [company / title / bullets | dates].
    Within a row, the header lines of every cell come first and the bullets
    after, so the dates cell stays with the company and title instead of
    landing after the bullets. Cell paragraphs keep their list (bullet) style.
    """
    out: list[dict[str, Any]] = []
    for row in table.rows:
        seen: set[int] = set()
        heads: list[dict[str, Any]] = []
        bullets: list[dict[str, Any]] = []
        for cell in row.cells:
            if id(cell._tc) in seen:  # merged cells repeat the same cell
                continue
            seen.add(id(cell._tc))
            for p in cell.paragraphs:
                item = _docx_paragraph(p)
                if item is None:
                    continue
                for sub in item["text"].splitlines():  # soft line breaks
                    if sub.strip():
                        target = bullets if item["text"].startswith("\u2022 ") else heads
                        target.append(item | {"text": sub.strip()})
            for nested in cell.tables:
                bullets += _docx_table_lines(nested)
        out += heads + bullets
    return out


def _extract_docx(data: bytes) -> dict[str, Any]:
    import docx
    from docx.opc.constants import RELATIONSHIP_TYPE as RT
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    document = docx.Document(io.BytesIO(data))
    lines: list[dict[str, Any]] = []

    # Contact details often live in the page header.
    seen_headers: set[int] = set()
    for section in document.sections:
        header = section.header
        if id(header.part) in seen_headers or header.is_linked_to_previous:
            continue
        seen_headers.add(id(header.part))
        for p in header.paragraphs:
            if (item := _docx_paragraph(p)) is not None:
                lines.append(item)
        for table in header.tables:
            for row in table.rows:
                cells = [c.text.strip() for c in row.cells if c.text.strip()]
                if cells:
                    lines.append({"text": " | ".join(dict.fromkeys(cells)), "bold": False,
                                  "size": 0.0, "heading_style": False})  # fmt: skip

    for block in document.iter_inner_content():
        if isinstance(block, Paragraph):
            if (item := _docx_paragraph(block)) is not None:
                lines.append(item)
        elif isinstance(block, Table):
            lines += _docx_table_lines(block)
        if len(lines) >= _MAX_LINES:
            break

    links = [
        rel.target_ref
        for rel in document.part.rels.values()
        if rel.reltype == RT.HYPERLINK and rel.is_external
    ]
    return {"ok": True, "page_count": 0, "lines": lines, "links": links, "findings": []}


# -------------------------------------------------------------------- entry
def child_main(conn: Any, file_type: str, data: bytes, options: dict[str, Any]) -> None:
    """Process entry point: extract and send exactly one result dict."""
    try:
        _limit_resources(options["memory_mb"], options["cpu_seconds"])
        if file_type == "pdf":
            result = _extract_pdf(data, options["max_pages"])
        elif file_type == "docx":
            result = _extract_docx(data)
        else:
            result = {"ok": False, "error": "unsupported", "message": file_type}
    except MemoryError:
        result = {"ok": False, "error": "too_complex", "message": "The file is too complex."}
    except Exception as exc:  # noqa: BLE001 - reported to the parent, which decides
        result = {
            "ok": False,
            "error": "unreadable",
            "message": f"{type(exc).__name__}: {exc}"[:500],
            "trace": traceback.format_exc(limit=5)[-2000:],
        }
    try:
        conn.send(result)
    finally:
        conn.close()
