"""Deterministic parsing engine: dates, skills, sections, entries, confidence."""

from datetime import date

import pytest

from app.documents.sandbox import ExtractedDocument, ExtractedLine
from app.parsing import entries
from app.parsing.contact import extract_contact, find_phone, looks_like_name
from app.parsing.dates import find_date_range, total_months
from app.parsing.parser import normalize_line, parse_document, weak_sections
from app.parsing.sections import match_section, split_sections
from app.parsing.skills import dedupe_skills, find_skills, normalize_skill, split_skill_list
from app.schemas.parsed_resume import ParsedResume, check_size_limits


def doc(*texts: str, headings: set[str] = frozenset()) -> ExtractedDocument:
    lines = [ExtractedLine(text=t, bold=t in headings, size=12.0 if t in headings else 10.0)
             for t in texts]  # fmt: skip
    return ExtractedDocument(file_type="pdf", page_count=1, lines=lines)


# ----------------------------------------------------------------- dates
@pytest.mark.parametrize(
    ("text", "start", "end", "current"),
    [
        ("Jan 2021 - Present", "2021-01", None, True),
        ("June 2017 – December 2020", "2017-06", "2020-12", False),
        ("Sept. 2019 to Aug 2021", "2019-09", "2021-08", False),
        ("03/2018 - 06/2020", "2018-03", "2020-06", False),
        ("2019-04 — 2020-01", "2019-04", "2020-01", False),
        ("2013 - 2017", "2013", "2017", False),
        ("Summer 2019", None, "2019-06", False),
        ("Acme | Feb 2020 - Current", "2020-02", None, True),
        ("2021 - 2019", "2019", "2021", False),  # reversed range is fixed
    ],
)
def test_date_ranges(text, start, end, current):
    dr = find_date_range(text)
    assert dr and (dr.start, dr.end, dr.is_current) == (start, end, current)


def test_no_date_in_plain_text():
    assert find_date_range("Led a team of 12 engineers") is None


def test_total_months_merges_overlaps():
    today = date(2026, 11, 1)
    assert total_months([("2021-01", None, True), ("2017-06", "2020-12", False)], today) == 114
    assert total_months([("2019", "2021", False), ("2020-06", "2022-01", False)], today) == 37
    assert total_months([(None, "2020", False)], today) == 0


# ---------------------------------------------------------------- skills
def test_skill_normalisation_and_mining():
    assert normalize_skill("postgres") == "PostgreSQL"
    assert normalize_skill("k8s") == "Kubernetes"
    assert normalize_skill("Some Niche Tool") == "Some Niche Tool"
    assert dedupe_skills(["postgres", "PostgreSQL", "k8s"]) == ["PostgreSQL", "Kubernetes"]
    found = find_skills("Shipped Node.js and C++ services; go to market with Postgres on k8s.")
    assert found == ["Node.js", "C++", "PostgreSQL", "Kubernetes"]
    assert "Go" not in found  # ambiguous: only from explicit lists


def test_split_skill_list():
    assert split_skill_list("Languages: Python, Go") == ("Languages", ["Python", "Go"])
    _, items = split_skill_list("Docker (Compose, Swarm) • CI/CD | TCP/IP")
    assert items == ["Docker", "Compose", "Swarm", "CI/CD", "TCP/IP"]


# ------------------------------------------------------------- sections
@pytest.mark.parametrize(
    ("text", "section"),
    [
        ("WORK EXPERIENCE", "experience"),
        ("Professional Experience:", "experience"),
        ("Technical Skills", "skills"),
        ("Licenses & Certifications", "certifications"),
        ("Honors and Awards", "awards"),
        ("Educaton", "education"),  # typo tolerated
        ("Led migration of services", None),
    ],
)
def test_match_section(text, section):
    assert match_section(text) == section


def test_plain_text_headings_without_styling():
    d = doc("Ana Silva", "ana@example.com", "Experience", "Engineer at Initech", "Education",
            "Some University")  # fmt: skip
    names = [s.name for s in split_sections(d.lines)]
    assert names == ["header", "experience", "education"]


# --------------------------------------------------------------- contact
def test_contact_from_header():
    header = [
        ExtractedLine("SAN FRANCISCO, CA", size=10),
        ExtractedLine("MARIA DE LA CRUZ", bold=True, size=20),
        ExtractedLine("maria@delacruz.io • +44 20 7946 0958 • delacruz.io"),
        ExtractedLine("linkedin.com/in/maria-dlc"),
    ]
    c = extract_contact(header, "", [])
    assert c.name == "Maria de la Cruz"
    assert c.email == "maria@delacruz.io"
    assert c.phone == "+44 20 7946 0958"
    assert c.location == "SAN FRANCISCO, CA" or c.location
    assert c.linkedin == "https://www.linkedin.com/in/maria-dlc"
    assert c.portfolio is None  # the email's own domain is not a portfolio


@pytest.mark.parametrize(
    ("text", "ok"),
    [("Jordan Rivera", True), ("Mary-Jane O'Neil", True), ("J. R. R. Tolkien", True),
     ("Senior Software Engineer at Acme", False), ("jordan@x.com", False),
     ("Team of 12", False), ("Rivera", False)],
)  # fmt: skip
def test_looks_like_name(text, ok):
    assert looks_like_name(text) is ok


def test_phone_ignores_dates_and_numbers():
    assert find_phone("2019 - 2021, managed $2,000,000 budget") is None
    assert find_phone("Call (415) 555-0142") == "(415) 555-0142"


# ------------------------------------------------------------ experience
def test_experience_title_at_company():
    out = entries.parse_experience(
        ["Data Scientist at Initech LLC (Austin, TX)", "Mar 2019 - Present",
         "• Built churn models in Python and scikit-learn"]
    )  # fmt: skip
    (e,) = out
    assert (e.title, e.company, e.start_date, e.is_current) == (
        "Data Scientist", "Initech LLC", "2019-03", True)  # fmt: skip
    assert e.skills == ["Python", "scikit-learn"]


def test_experience_company_first_and_wrapped_bullets():
    out = entries.parse_experience(
        [
            "Globex Corporation | Remote",
            "Product Manager | 01/2018 - 12/2020",
            "- Owned the payments roadmap across three teams and",
            "shipped five major launches",
            "Hooli Inc",
            "Associate Product Manager, 2016 - 2017",
            "- Ran A/B testing for onboarding",
        ]
    )
    assert [(e.company, e.title) for e in out] == [
        ("Globex Corporation", "Product Manager"),
        ("Hooli Inc", "Associate Product Manager"),
    ]
    assert out[0].location == "Remote"
    assert out[0].bullets == [
        "Owned the payments roadmap across three teams and shipped five major launches"
    ]
    assert (out[1].start_date, out[1].end_date) == ("2016", "2017")


# ------------------------------------------------------------- education
def test_education_variants():
    out = entries.parse_education(
        [
            "Massachusetts Institute of Technology, 2015",
            "Bachelor of Science in Mechanical Engineering",
            "Magna Cum Laude",
            "Stanford University | M.S. Computer Science | 2016 - 2018 | GPA: 3.9/4.0",
        ]
    )
    mit, stanford = out
    assert mit.institution == "Massachusetts Institute of Technology"
    assert mit.degree == "Bachelor of Science"
    assert mit.field_of_study == "Mechanical Engineering"
    assert mit.end_date == "2015" and mit.honors == ["Magna Cum Laude"]
    assert stanford.institution == "Stanford University"
    assert (stanford.degree, stanford.field_of_study) == ("M.S.", "Computer Science")
    assert (stanford.start_date, stanford.end_date, stanford.gpa) == ("2016", "2018", "3.9")


# ------------------------------------------------------ other list sections
def test_lists_certs_publications_awards_projects():
    (cert,) = entries.parse_certifications(
        ["Certified Kubernetes Administrator (CKA) | CNCF | 2023"]
    )
    assert (cert.name, cert.issuer, cert.date) == (
        "Certified Kubernetes Administrator (CKA)",
        "CNCF",
        "2023",
    )
    (pub,) = entries.parse_publications(["“Fast Joins”, VLDB 2021"])
    assert (pub.title, pub.venue, pub.date) == ("Fast Joins", "VLDB", "2021")
    (award,) = entries.parse_awards(["• Dean's List, 2014"])
    assert (award.title, award.date) == ("Dean's List", "2014")
    (proj,) = entries.parse_projects(
        [
            "Ledger: double-entry accounting API (github.com/me/ledger)",
            "• Written in Go and PostgreSQL",
        ]
    )
    assert proj.name == "Ledger" and proj.url == "https://github.com/me/ledger"
    assert proj.description == "double-entry accounting API" and "PostgreSQL" in proj.technologies


def test_skills_section_with_sentences():
    skills, groups = entries.parse_skills(
        [
            "Languages: Python, SQL",
            "Experienced with Kubernetes, Terraform and modern CI/CD practices",
        ]
    )
    assert skills[:2] == ["Python", "SQL"] and {"Kubernetes", "Terraform"} <= set(skills)
    assert groups[0].name == "Languages"


# --------------------------------------------------------------- parser
def test_normalize_line_cleans_artifacts():
    assert normalize_line("(cid:127) Built APIs") == "• Built APIs"
    assert normalize_line("Py​thon  (cid:3) dev") == "Python dev"


def test_full_parse_confidence_and_no_llm_needed():
    d = doc(
        "Ana Silva", "Lisbon, Portugal | ana@example.com",
        "EXPERIENCE", "Backend Engineer, Initech Ltd", "2019 - Present", "• Built Python APIs",
        "EDUCATION", "University of Lisbon", "BSc Computer Science, 2015 - 2019",
        "SKILLS", "Python, Django, PostgreSQL",
        headings={"EXPERIENCE", "EDUCATION", "SKILLS"},
    )  # fmt: skip
    result = parse_document(d)
    r = result.resume
    assert r.contact.name == "Ana Silva" and r.contact.location == "Lisbon, Portugal"
    assert r.experience[0].company == "Initech Ltd"
    assert r.education[0].degree == "BSc"
    assert r.skills == ["Python", "Django", "PostgreSQL"]
    assert r.meta.confidence > 0.9
    assert weak_sections(result) == []


def test_weak_sections_are_targeted():
    d = doc(
        "Ana Silva", "ana@example.com",
        "EXPERIENCE", "Did many things for many years with many people", "and other things too",
        "SKILLS", "Python",
        headings={"EXPERIENCE", "SKILLS"},
    )  # fmt: skip
    result = parse_document(d)
    assert weak_sections(result) == ["experience"]


def test_unstructured_document_goes_to_llm_whole():
    d = doc("some text without structure", "more text", "even more text")
    result = parse_document(d)
    assert weak_sections(result) is None
    assert "No standard resume sections were recognised." in result.resume.meta.warnings


# ------------------------------------------------------- schema / limits
def test_size_limits():
    ok = ParsedResume(skills=["Python"] * 10).model_dump()
    check_size_limits(ok)
    with pytest.raises(ValueError, match="longer than"):
        check_size_limits({"summary": "x" * 6000})
    with pytest.raises(ValueError, match="more than"):
        check_size_limits({"skills": ["a"] * 400})
    with pytest.raises(ValueError, match="larger than"):
        check_size_limits({"experience": [{"bullets": ["x" * 4000] * 60}]})


def test_only_http_links_survive():
    r = ParsedResume.model_validate(
        {
            "contact": {
                "linkedin": "javascript:alert(1)",
                "portfolio": "https://me.dev",
                "other_links": ["data:text/html,x", "http://ok.test"],
            },
            "projects": [{"name": "P", "url": "JAVASCRIPT:alert(1)"}],
        }
    )
    assert r.contact.linkedin is None and r.contact.portfolio == "https://me.dev"
    assert r.contact.other_links == ["http://ok.test"]
    assert r.projects[0].url is None
