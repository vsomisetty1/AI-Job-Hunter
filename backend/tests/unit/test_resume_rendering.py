"""Unit: Agent 7 renders resumes and letters as ATS-readable PDF and DOCX."""

import io
from datetime import date

import docx
import pdfplumber
import pytest

from app.agents.agent_7_resume_generation import (
    LetterDoc,
    date_range,
    format_month,
    render_letter_docx,
    render_letter_files,
    render_letter_pdf,
    render_resume_docx,
    render_resume_files,
    render_resume_pdf,
    resume_blocks,
)
from app.schemas.parsed_resume import ParsedResume
from tests.fixtures.resumes import sample_resume


def pdf_lines(data: bytes) -> list[str]:
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        return [line for p in pdf.pages for line in (p.extract_text() or "").splitlines()]


def docx_lines(data: bytes) -> list[str]:
    return [p.text for p in docx.Document(io.BytesIO(data)).paragraphs]


@pytest.mark.parametrize(
    ("value", "shown"),
    [("2021-03", "Mar 2021"), ("2021", "2021"), (None, ""), ("2021-13", "2021")],
)
def test_format_month(value, shown):
    assert format_month(value) == shown


def test_date_range():
    assert date_range("2020-03", None, True) == "Mar 2020 – Present"
    assert date_range("2016-06", "2020-02", False) == "Jun 2016 – Feb 2020"
    assert date_range(None, "2016", False) == "2016"


def test_blocks_follow_standard_section_order():
    sections = [b.text for b in resume_blocks(sample_resume()) if b.kind == "section"]
    assert sections == ["Summary", "Experience", "Skills", "Projects", "Education"]


def test_pdf_is_text_in_reading_order_and_deterministic():
    data = render_resume_pdf(sample_resume())
    assert data.startswith(b"%PDF") and data == render_resume_pdf(sample_resume())
    lines = pdf_lines(data)
    assert lines[0] == "Jordan Rivera"
    assert "jordan@example.com" in lines[1]
    order = [lines.index(x) for x in ("SUMMARY", "EXPERIENCE", "SKILLS", "PROJECTS", "EDUCATION")]
    assert order == sorted(order)
    assert "Senior Software Engineer — Acme Payments" in lines
    assert "San Francisco, CA | Mar 2020 – Present" in lines
    # Plain "-" bullets: no glyphs an ATS cannot read.
    assert "- Mentored 4 engineers through onboarding" in lines
    assert not any("(cid:" in line for line in lines)
    assert "Other: postgres, AWS" in lines  # skills outside every group are not lost


def test_docx_has_the_same_content_with_word_bullets():
    data = render_resume_docx(sample_resume())
    paragraphs = docx.Document(io.BytesIO(data)).paragraphs
    texts = [p.text for p in paragraphs]
    assert texts[0] == "Jordan Rivera" and "EXPERIENCE" in texts
    bullet = next(p for p in paragraphs if p.text == "Mentored 4 engineers through onboarding")
    assert bullet.style.name == "List Bullet"
    assert docx.Document(io.BytesIO(data)).core_properties.title == "Jordan Rivera - Resume"


def test_markup_in_resume_text_is_escaped_not_interpreted():
    resume = sample_resume(summary="Built <b>things</b> & tools <font size=40>big</font>")
    lines = pdf_lines(render_resume_pdf(resume))
    assert "Built <b>things</b> & tools <font size=40>big</font>" in lines


def test_empty_resume_still_renders():
    assert pdf_lines(render_resume_pdf(ParsedResume())) == ["Resume"]
    assert render_resume_docx(ParsedResume()).startswith(b"PK")


LETTER = LetterDoc(
    sender_name="Jordan Rivera",
    sender_contact="jordan@example.com",
    date=date(2026, 11, 27),
    recipient="Hiring team, Stripe",
    greeting="Dear Stripe hiring team,",
    paragraphs=["First paragraph.", "Second paragraph."],
)


def test_letter_pdf_and_docx():
    lines = pdf_lines(render_letter_pdf(LETTER))
    assert lines[:3] == ["Jordan Rivera", "jordan@example.com", "November 27, 2026"]
    assert lines[-2:] == ["Sincerely,", "Jordan Rivera"]
    assert docx_lines(render_letter_docx(LETTER))[-2:] == ["Sincerely,", "Jordan Rivera"]


async def test_async_entry_points_render_both_formats():
    resume = await render_resume_files(sample_resume())
    letter = await render_letter_files(LETTER)
    assert resume.pdf.startswith(b"%PDF") and resume.docx.startswith(b"PK")
    assert letter.pdf.startswith(b"%PDF") and letter.docx.startswith(b"PK")
