"""Agent 7: render resumes and cover letters as PDF and DOCX.

ATS-friendly by construction: one column, real text (no images, tables,
text boxes, headers/footers or columns), standard fonts, plain section names
("Experience", "Education", "Skills"), one bullet per line, dates as
"Jan 2021 – Present". PDF bullets are a plain "-": the built-in fonts encode
"•" in a way text extractors (and so ATS parsers) read as junk. DOCX uses
Word's own bulleted list style. The same `ParsedResume` structure renders the original
(parsed) version and every tailored version, so both look the same.

Rendering is CPU work; `render_*_files` run it in a worker thread.
"""

import asyncio
import io
from dataclasses import dataclass, field
from datetime import date
from xml.sax.saxutils import escape

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt, RGBColor
from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    Flowable,
    HRFlowable,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
)

from app.schemas.parsed_resume import ExperienceEntry, ParsedResume

MONTHS_SHORT = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
PDF_TYPE = "application/pdf"
DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

FONT, FONT_BOLD = "Helvetica", "Helvetica-Bold"
ACCENT = "#1f2937"

_STYLES = {
    "name": ParagraphStyle("name", fontName=FONT_BOLD, fontSize=17, leading=21,
                           alignment=TA_CENTER, textColor=HexColor(ACCENT)),
    "contact": ParagraphStyle("contact", fontName=FONT, fontSize=9.5, leading=12,
                              alignment=TA_CENTER, textColor=HexColor("#374151")),
    "section": ParagraphStyle("section", fontName=FONT_BOLD, fontSize=11, leading=14,
                              spaceBefore=9, spaceAfter=1, textColor=HexColor(ACCENT)),
    "role": ParagraphStyle("role", fontName=FONT_BOLD, fontSize=10.5, leading=13, spaceBefore=4),
    "meta": ParagraphStyle("meta", fontName=FONT, fontSize=9.5, leading=12,
                           textColor=HexColor("#4b5563")),
    "body": ParagraphStyle("body", fontName=FONT, fontSize=10, leading=13),
    "bullet": ParagraphStyle("bullet", fontName=FONT, fontSize=10, leading=13, leftIndent=12,
                             bulletIndent=2, spaceBefore=1),
    "letter": ParagraphStyle("letter", fontName=FONT, fontSize=11, leading=15, spaceAfter=9),
}  # fmt: skip


# ------------------------------------------------------------------ text
def format_month(value: str | None) -> str:
    """'2021-03' -> 'Mar 2021'; '2021' -> '2021'."""
    if not value:
        return ""
    year, _, month = value.partition("-")
    if month.isdigit() and 1 <= int(month) <= 12:
        return f"{MONTHS_SHORT[int(month) - 1]} {year}"
    return year


def date_range(start: str | None, end: str | None, current: bool) -> str:
    s, e = format_month(start), "Present" if current else format_month(end)
    return f"{s} – {e}" if s and e else s or e


def contact_line(resume: ParsedResume) -> str:
    c = resume.contact
    parts = [c.email, c.phone, c.location, c.linkedin, c.github, c.portfolio, *c.other_links]
    return "  |  ".join(p for p in parts if p)


def role_heading(e: ExperienceEntry) -> str:
    return " — ".join(x for x in (e.title, e.company) if x) or "Experience"


def role_meta(e: ExperienceEntry) -> str:
    return "  |  ".join(x for x in (e.location, date_range(e.start_date, e.end_date,
                                                           e.is_current)) if x)  # fmt: skip


@dataclass(frozen=True)
class Block:
    """One renderer-independent piece of a document."""

    kind: str  # name | contact | section | role | meta | body | bullet
    text: str


def resume_blocks(resume: ParsedResume) -> list[Block]:
    """The resume as an ordered list of blocks (shared by PDF and DOCX)."""
    out: list[Block] = []
    if resume.contact.name:
        out.append(Block("name", resume.contact.name))
    if line := contact_line(resume):
        out.append(Block("contact", line))
    if resume.summary:
        out += [Block("section", "Summary"), Block("body", resume.summary)]
    if resume.experience:
        out.append(Block("section", "Experience"))
        for e in resume.experience:
            out.append(Block("role", role_heading(e)))
            if meta := role_meta(e):
                out.append(Block("meta", meta))
            out += [Block("bullet", b) for b in e.bullets]
    if resume.skill_groups:
        out.append(Block("section", "Skills"))
        out += [Block("body", f"{g.name}: {', '.join(g.skills)}") for g in resume.skill_groups
                if g.skills]  # fmt: skip
        # Skills outside every group would otherwise be missing from the file.
        grouped = {s.casefold() for g in resume.skill_groups for s in g.skills}
        rest = [s for s in resume.skills if s.casefold() not in grouped]
        if rest:
            out.append(Block("body", f"Other: {', '.join(rest)}"))
    elif resume.skills:
        out += [Block("section", "Skills"), Block("body", ", ".join(resume.skills))]
    if resume.projects:
        out.append(Block("section", "Projects"))
        for p in resume.projects:
            out.append(Block("role", p.name))
            meta = "  |  ".join(x for x in (", ".join(p.technologies), p.url or "") if x)
            if meta:
                out.append(Block("meta", meta))
            if p.description:
                out.append(Block("body", p.description))
            out += [Block("bullet", b) for b in p.bullets]
    if resume.education:
        out.append(Block("section", "Education"))
        for ed in resume.education:
            degree = " in ".join(x for x in (ed.degree, ed.field_of_study) if x)
            out.append(Block("role", " — ".join(x for x in (degree, ed.institution) if x)
                             or "Education"))  # fmt: skip
            meta = "  |  ".join(
                x for x in (date_range(ed.start_date, ed.end_date, False),
                            f"GPA {ed.gpa}" if ed.gpa else "") if x
            )  # fmt: skip
            if meta:
                out.append(Block("meta", meta))
            out += [Block("bullet", h) for h in ed.honors]
    if resume.certifications:
        out.append(Block("section", "Certifications"))
        for c in resume.certifications:
            bits = [c.name, c.issuer or "", format_month(c.date)]
            out.append(Block("bullet", " — ".join(b for b in bits if b)))
    if resume.publications:
        out.append(Block("section", "Publications"))
        for pub in resume.publications:
            bits = [pub.title, pub.venue or "", format_month(pub.date)]
            out.append(Block("bullet", " — ".join(b for b in bits if b)))
    if resume.awards:
        out.append(Block("section", "Awards"))
        for a in resume.awards:
            bits = [a.title, a.issuer or "", format_month(a.date)]
            out.append(Block("bullet", " — ".join(b for b in bits if b)))
    if resume.languages:
        out += [Block("section", "Languages"), Block("body", ", ".join(resume.languages))]
    for o in resume.other_sections:
        out.append(Block("section", o.title))
        out += [Block("bullet", line) for line in o.lines]
    return out


@dataclass(frozen=True)
class LetterDoc:
    sender_name: str
    sender_contact: str
    date: date
    recipient: str
    greeting: str
    paragraphs: list[str] = field(default_factory=list)
    closing: str = "Sincerely,"


# ------------------------------------------------------------------ PDF
def _pdf(story: list[Flowable], title: str, author: str) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=LETTER, leftMargin=0.7 * inch, rightMargin=0.7 * inch,
        topMargin=0.6 * inch, bottomMargin=0.6 * inch, title=title, author=author,
        invariant=1,
    )  # fmt: skip
    doc.build(story)
    return buf.getvalue()


def render_resume_pdf(resume: ParsedResume) -> bytes:
    story: list[Flowable] = []
    role: list[Flowable] = []

    def flush() -> None:
        if role:
            story.append(KeepTogether(list(role)))
            role.clear()

    for b in resume_blocks(resume):
        text = escape(b.text)
        if b.kind == "section":
            flush()
            story += [Paragraph(text.upper(), _STYLES["section"]),
                      HRFlowable(width="100%", thickness=0.6, color=HexColor("#9ca3af"),
                                 spaceAfter=3)]  # fmt: skip
        elif b.kind == "role":
            flush()
            role.append(Paragraph(text, _STYLES["role"]))
        elif b.kind == "bullet":
            p = Paragraph(text, _STYLES["bullet"], bulletText="-")
            # Keep a role's heading with its first lines; long roles may split.
            (role if role and len(role) < 4 else story).append(p)
            if len(role) >= 4:
                flush()
        else:
            target = role if role and b.kind == "meta" else story
            if target is story:
                flush()
            target.append(Paragraph(text, _STYLES[b.kind]))
    flush()
    if not story:
        story.append(Paragraph("Resume", _STYLES["body"]))
    name = resume.contact.name or "Resume"
    return _pdf(story, f"{name} - Resume", name)


def render_letter_pdf(letter: LetterDoc) -> bytes:
    s = _STYLES
    story: list[Flowable] = [
        Paragraph(escape(letter.sender_name), s["name"]),
        Paragraph(escape(letter.sender_contact), s["contact"]) if letter.sender_contact
        else Spacer(1, 0),
        Spacer(1, 16),
        Paragraph(escape(letter.date.strftime("%B %-d, %Y")), s["letter"]),
        Paragraph(escape(letter.recipient), s["letter"]),
        Paragraph(escape(letter.greeting), s["letter"]),
        *[Paragraph(escape(p), s["letter"]) for p in letter.paragraphs],
        Paragraph(escape(letter.closing), s["letter"]),
        Paragraph(escape(letter.sender_name), s["letter"]),
    ]  # fmt: skip
    return _pdf(story, f"{letter.sender_name} - Cover letter", letter.sender_name)


# ------------------------------------------------------------------ DOCX
def _docx_base(title: str, author: str) -> object:
    doc = Document()
    normal = doc.styles["Normal"]
    normal.font.name = "Calibri"
    normal.font.size = Pt(10.5)
    normal.paragraph_format.space_after = Pt(2)
    for section in doc.sections:
        section.left_margin = section.right_margin = Pt(50)
        section.top_margin = section.bottom_margin = Pt(43)
    doc.core_properties.title = title
    doc.core_properties.author = author
    return doc


def _save(doc: object) -> bytes:
    buf = io.BytesIO()
    doc.save(buf)  # type: ignore[attr-defined]
    return buf.getvalue()


def render_resume_docx(resume: ParsedResume) -> bytes:
    name = resume.contact.name or "Resume"
    doc = _docx_base(f"{name} - Resume", name)
    for b in resume_blocks(resume):
        if b.kind == "bullet":
            doc.add_paragraph(b.text, style="List Bullet")  # type: ignore[attr-defined]
            continue
        p = doc.add_paragraph()  # type: ignore[attr-defined]
        run = p.add_run(b.text.upper() if b.kind == "section" else b.text)
        if b.kind == "name":
            run.bold, run.font.size = True, Pt(17)
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        elif b.kind == "contact":
            run.font.size = Pt(9.5)
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        elif b.kind == "section":
            run.bold, run.font.size = True, Pt(11)
            run.font.color.rgb = RGBColor(0x1F, 0x29, 0x37)
            p.paragraph_format.space_before = Pt(9)
        elif b.kind == "role":
            run.bold = True
            p.paragraph_format.space_before = Pt(4)
        elif b.kind == "meta":
            run.font.size = Pt(9.5)
            run.font.color.rgb = RGBColor(0x4B, 0x55, 0x63)
    return _save(doc)


def render_letter_docx(letter: LetterDoc) -> bytes:
    doc = _docx_base(f"{letter.sender_name} - Cover letter", letter.sender_name)
    head = doc.add_paragraph()  # type: ignore[attr-defined]
    run = head.add_run(letter.sender_name)
    run.bold, run.font.size = True, Pt(16)
    if letter.sender_contact:
        doc.add_paragraph(letter.sender_contact)  # type: ignore[attr-defined]
    for text in (letter.date.strftime("%B %-d, %Y"), letter.recipient, letter.greeting,
                 *letter.paragraphs, letter.closing, letter.sender_name):  # fmt: skip
        p = doc.add_paragraph(text)  # type: ignore[attr-defined]
        p.paragraph_format.space_after = Pt(9)
    return _save(doc)


# ------------------------------------------------------------ async entry
@dataclass(frozen=True)
class RenderedFiles:
    pdf: bytes
    docx: bytes


async def render_resume_files(resume: ParsedResume) -> RenderedFiles:
    pdf, docx = await asyncio.gather(
        asyncio.to_thread(render_resume_pdf, resume), asyncio.to_thread(render_resume_docx, resume)
    )
    return RenderedFiles(pdf, docx)


async def render_letter_files(letter: LetterDoc) -> RenderedFiles:
    pdf, docx = await asyncio.gather(
        asyncio.to_thread(render_letter_pdf, letter), asyncio.to_thread(render_letter_docx, letter)
    )
    return RenderedFiles(pdf, docx)
