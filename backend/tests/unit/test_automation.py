"""Application automation, pure parts: labels, semantic matching, option
choice, planning rules (never invent, never tick consent, never guess
self-identification), recovery, checkpoints, the session registry, adapters.

Labels below are copied from live Greenhouse, Lever and Ashby forms."""

import asyncio
import uuid

import pytest
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeout

from app.automation.browser_manager import SessionRegistry
from app.automation.checkpoints import Checkpoint, form_signature
from app.automation.field_matcher import (
    AnswerFact,
    ApplicantFacts,
    choose_option,
    concept_of,
    plan_field,
    plan_form,
    yes_no,
)
from app.automation.fields import FieldOption, FormField, clean_label, marks_required
from app.automation.platforms import adapter_for
from app.automation.recovery import (
    AtsChangedError,
    JobClosedError,
    UploadFailedError,
    classify,
    hint,
    with_retries,
)

FACTS = ApplicantFacts(
    full_name="Jordan Rivera", first_name="Jordan", last_name="Rivera",
    email="jordan@example.com", phone="+1 415 555 0100", location="San Francisco, CA",
    country="United States", linkedin="https://linkedin.com/in/jr", github="https://github.com/jr",
    current_company="Acme", current_title="Senior Engineer", years_experience=6,
    salary_target=180000,
    answers=(
        AnswerFact("work_authorization", "Authorized?", "Yes, I am authorized to work.", True),
        AnswerFact("sponsorship", "Sponsorship?", "No, I do not require sponsorship.", True),
        AnswerFact("relocation", "Relocate?", "Please answer this yourself.", False),
        AnswerFact("salary_expectations", "Salary?", "My target base salary is USD 180,000.", True),
        AnswerFact("experience:Python", "Python?", "About 5 years: I have used Python in 2 roles.",
                   True),
        AnswerFact("why_company", "Why us?", "Please write this yourself.", False),
    ),
    has_resume_file=True, has_cover_letter_file=False, cover_letter_text="Dear team, ...",
)  # fmt: skip


def field(label: str, kind: str = "text", *, options=(), required=False, key=None, **kw):
    return FormField(
        key=key or label.lower(), handle="f1", kind=kind, label=label, required=required,
        options=tuple(FieldOption(o) for o in options), **kw,
    )  # fmt: skip


# ------------------------------------------------------------------ labels
def test_labels_lose_required_markers_and_trailing_widget_text():
    assert clean_label("Email*") == "Email"
    assert clean_label("Current location ✱") == "Current location"
    # A wrapping <label> holds the question and the widget's own text (Lever).
    assert clean_label("Resume/CV ✱ ATTACH RESUME/CV Couldn't auto-read resume.") == "Resume/CV"
    assert marks_required("Resume/CV ✱ ATTACH RESUME/CV") and not marks_required("Phone")


def test_from_dom_prefers_a_specific_label_over_a_button_caption():
    f = FormField.from_dom(
        {"key": "resume", "handle": "f3", "kind": "file", "labels": ["Attach", "Resume/CV *"]}
    )
    assert f.label == "Resume/CV" and f.required and f.hints == ("Attach",)


# ---------------------------------------------------------------- concepts
@pytest.mark.parametrize(
    ("label", "concept"),
    [
        ("First Name", "first_name"),
        ("Preferred First Name", "preferred_name"),
        ("Legal Name", "full_name"),
        ("Full name", "full_name"),
        ("LinkedIn Profile", "linkedin"),
        ("Location (City)", "location"),
        ("Where do you plan on working from (for payroll tax purposes)?", "location"),
        ("Are you authorized to work lawfully in the United States for Duolingo?",
         "work_authorization"),
        ("Will you now or in the future require sponsorship for employment visa status "
         "(e.g., H-1B, etc.)?", "sponsorship"),
        ("Please tell us how you heard about this opportunity.", "how_heard"),
        ("Where did you hear about this job?", "how_heard"),
        ("How would you describe your gender identity? (mark all that apply)", "eeo"),
        ("Veteran status", "eeo"),
        ("Why do you want to work at Palantir?", "why_company"),
        ("Do you have a minimum of 7 years of experience building software?", "years_experience"),
        ("Additional information", "additional_info"),
        ("How do you pronounce your name? (e.g., 'An-na' or 'Ah-na')", "pronunciation"),
        ("Based on the job description, which team are you most interested in?", None),
    ],
)  # fmt: skip
def test_concepts_from_real_labels(label, concept):
    assert concept_of(field(label)) == concept


def test_input_types_and_autocomplete_decide_before_words():
    assert concept_of(field("Contact", "email")) == "email"
    assert concept_of(field("Your info", autocomplete="given-name")) == "first_name"


def test_hints_only_count_when_the_label_is_empty():
    noisy = field("Which team?", hints=("244 results found", "Phone"))
    assert concept_of(noisy) is None
    assert concept_of(field("", hints=("Email address",))) == "email"


# ----------------------------------------------------------------- options
def test_choose_option_by_meaning():
    assert choose_option(True, ["Yes", "No"]) == 0
    assert choose_option(False, ["Yes, I will", "No, I won't"]) == 1
    assert choose_option("United States", ["United Kingdom +44", "United States +1"]) == 1
    assert choose_option("Senior", ["Junior", "Mid", "Staff"]) is None  # never a near miss
    assert choose_option("x", ["A", "Company Careers Page"],
                         preferred=[r"careers? (page|site)"]) == 1  # fmt: skip
    assert yes_no("Yes, I am authorized") is True and yes_no("Maybe") is None


# --------------------------------------------------------------- planning
def test_contact_and_profile_facts_fill_text_fields():
    assert plan_field(field("First Name"), FACTS).value == "Jordan"
    assert plan_field(field("Legal Name"), FACTS).value == "Jordan Rivera"
    assert plan_field(field("Current company"), FACTS).value == "Acme"
    p = plan_field(field("Email", "email"), FACTS)
    assert (p.status, p.value, p.source) == ("fill", "jordan@example.com", "resume")


def test_yes_no_questions_use_reviewed_answers_only():
    auth = field("Are you legally authorized to work in the country?", "radio",
                 options=("Yes", "No"), required=True)  # fmt: skip
    assert plan_field(auth, FACTS).value == "Yes"
    visa = field("Will you require sponsorship?", "combobox", required=True)
    assert plan_field(visa, FACTS).value is False  # chosen when the list opens
    # The relocation answer still needs review: never filled.
    move = field("Are you willing to relocate?", "radio", options=("Yes", "No"), required=True)
    plan = plan_field(move, FACTS)
    assert plan.status == "needs_you" and "relocate" in plan.reason


def test_unknown_required_questions_are_left_for_the_user():
    plan = plan_field(field("Which team are you most interested in?", required=True), FACTS)
    assert plan.status == "needs_you" and plan.value is None
    assert plan_field(field("Which team?"), FACTS).status == "skipped"  # optional: left blank
    # A "needs review" package answer is a placeholder, never typed.
    why = plan_field(field("Why do you want to work at Acme?", "textarea", required=True), FACTS)
    assert why.status == "needs_you"


def test_consent_and_lone_checkboxes_are_never_ticked():
    for f in (
        field("I agree to the privacy policy", "checkbox", required=True),
        field("SMS", "radio", options=("Yes - I consent to SMS", "No")),
        field("We may use AI notetakers.", "radio", options=("Yes, I consent", "No")),
    ):
        assert plan_field(f, FACTS).status == "consent"
    assert plan_field(field("Subscribe to updates", "checkbox"), FACTS).status == "skipped"


def test_self_identification_is_declined_or_left_blank():
    gender = field("Gender", "select", options=("Male", "Female", "I don't wish to answer"))
    plan = plan_field(gender, FACTS)
    assert (plan.value, plan.sensitive) == ("I don't wish to answer", True)
    disability = field("Disability status", "select",
                       options=("Yes", "No", "I do not want to answer"))  # fmt: skip
    assert plan_field(disability, FACTS).value == "I do not want to answer"
    no_decline = field("Veteran status", "select", options=("Veteran", "Not a veteran"))
    assert plan_field(no_decline, FACTS).status == "skipped"


def test_years_questions():
    general = field("Do you have a minimum of 5 years of experience building software?", "yes_no",
                    options=("Yes", "No"))  # fmt: skip
    assert plan_field(general, FACTS).value == "Yes"  # 6 years
    seven = field("Do you have a minimum of 7 years of experience?", "yes_no",
                  options=("Yes", "No"))  # fmt: skip
    assert plan_field(seven, FACTS).value == "No"
    # A named technology uses that skill's reviewed years, never the total.
    python = field("Do you have at least 5 years of experience with Python?", "yes_no",
                   options=("Yes", "No"))  # fmt: skip
    assert plan_field(python, FACTS).value == "Yes"
    aws = field("Do you have at least 3 years of experience with AWS?", "yes_no",
                options=("Yes", "No"), required=True)  # fmt: skip
    assert plan_field(aws, FACTS).status == "needs_you"
    assert plan_field(field("How many years of experience do you have?"), FACTS).value == "6"


def test_files_and_cover_letter_placement():
    assert plan_field(field("Resume/CV", "file"), FACTS).status == "upload"
    # No cover letter file in this package: the upload is left for the user...
    assert plan_field(field("Cover Letter", "file"), FACTS).status == "skipped"
    # ...and with no upload on the form the letter goes into "Additional information".
    plans = plan_form([field("Resume/CV", "file"), field("Additional information", "textarea")],
                      FACTS)  # fmt: skip
    assert plans[1].status == "fill" and plans[1].value == "Dear team, ..."
    # A form with a letter upload keeps "Additional information" empty.
    with_upload = ApplicantFacts(**{**FACTS.__dict__, "has_cover_letter_file": True})
    plans = plan_form([field("Cover Letter", "file"), field("Additional information", "textarea")],
                      with_upload)  # fmt: skip
    assert plans[0].status == "upload" and plans[1].status == "skipped"


def test_salary_and_how_heard():
    assert plan_field(field("Desired salary", "number"), FACTS).value == "180000"
    assert plan_field(field("Salary expectations"), FACTS).value == "180,000 USD"
    heard = field("How did you hear about us?", "select",
                  options=("LinkedIn", "Acme Careers Page", "Referral"))  # fmt: skip
    assert plan_field(heard, FACTS).value == "Acme Careers Page"


def test_an_option_that_does_not_match_is_not_picked():
    office = field("Which office location?", "select", options=("New York", "London"),
                   required=True)  # fmt: skip
    plan = plan_field(office, FACTS)  # "location" concept, but no option is San Francisco
    assert plan.status == "needs_you" and "None of the options" in plan.reason


# --------------------------------------------------------------- recovery
def test_failures_are_classified_with_actionable_messages():
    assert classify(PlaywrightTimeout("Timeout 30000ms exceeded")).kind == "timeout"
    crash = classify(PlaywrightError("Target page, context or browser has been closed"))
    assert crash.kind == "browser_crash" and crash.retryable
    assert classify(PlaywrightError("net::ERR_CONNECTION_RESET")).kind == "network"
    assert classify(JobClosedError("gone")).kind == "job_closed"
    assert not classify(AtsChangedError("x")).retryable
    assert not classify(UploadFailedError("x")).retryable
    assert classify(ValueError("boom")).kind == "internal"
    assert "apply twice" in hint("unconfirmed")


async def test_with_retries_repeats_only_transient_failures():
    calls = []

    async def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise PlaywrightTimeout("slow")
        return "ok"

    async def no_sleep(_s):
        return None

    retried = []

    async def on_retry(n, failure):
        retried.append((n, failure.kind))

    assert await with_retries(flaky, attempts=3, on_retry=on_retry, sleep=no_sleep) == "ok"
    assert retried == [(1, "timeout"), (2, "timeout")]

    async def closed():
        raise JobClosedError("closed")

    with pytest.raises(JobClosedError):
        await with_retries(closed, attempts=5, sleep=no_sleep)


def test_checkpoint_roundtrip_and_signature():
    ckpt = Checkpoint(step="filling", url="https://x", fields=[{"key": "email"}], attempt=2)
    again = Checkpoint.from_json(ckpt.as_json())
    assert again.step == "filling" and again.previous_value("email") == {"key": "email"}
    assert Checkpoint.from_json({"version": 99, "step": "review"}).step == "queued"
    assert form_signature(["a", "b"]) == form_signature(["b", "a"]) != form_signature(["a"])


async def test_registry_caps_open_sessions_and_finds_idle_ones():
    reg = SessionRegistry(max_sessions=1, idle_seconds=10)
    a, b = uuid.uuid4(), uuid.uuid4()
    await reg.acquire(a)
    waiting = asyncio.create_task(reg.acquire(b))
    await asyncio.sleep(0.01)
    assert not waiting.done()  # the second run waits for a slot
    await reg.release(a)
    await asyncio.wait_for(waiting, 1)
    assert reg.idle() == [] and reg.get(b) is None
    await reg.release(b)


# --------------------------------------------------------------- adapters
def test_application_urls():
    gh = adapter_for("greenhouse")
    assert gh.application_url("duolingo", "8584012002", "https://careers.duolingo.com/jobs/1") == (
        "https://job-boards.greenhouse.io/embed/job_app?for=duolingo&token=8584012002"
    )
    lever = adapter_for("lever")
    assert lever.application_url("acme", "id-1", None) == "https://jobs.lever.co/acme/id-1/apply"
    assert lever.application_url("acme", "id-1", "https://jobs.eu.lever.co/acme/id-1") == (
        "https://jobs.eu.lever.co/acme/id-1/apply"
    )
    ashby = adapter_for("ashby")
    # The slug is case-sensitive: the job's own URL wins.
    assert ashby.application_url("posthog", "j1", "https://jobs.ashbyhq.com/PostHog/j1") == (
        "https://jobs.ashbyhq.com/PostHog/j1/application"
    )
    assert adapter_for("workday") is None


def test_us_status_answers_only_explicit_us_questions():
    facts = ApplicantFacts(
        answers=(AnswerFact("work_authorization", "Status?", "US citizen.", True),)
    )
    us = field("Are you authorized to work lawfully in the United States?", "combobox")
    assert plan_field(us, facts).value is True
    other = field("Are you legally authorized to work in the country for which you are applying?",
                  "radio", options=("Yes", "No"), required=True)  # fmt: skip
    assert plan_field(other, facts).status == "needs_you"


# ------------------------------------------------- real-form lessons (validation run)
def test_location_pickers_expand_state_abbreviations():
    from app.automation.field_matcher import choose_location

    options = ["San Francisco, California, United States", "San Francisco Cajonos, Oaxaca, Mexico"]
    assert choose_location("San Francisco, CA", options) == 0
    assert choose_location("Austin, TX", ["Austin, Texas, US", "Austin, Minnesota, US"]) == 0
    assert choose_location("Springfield", ["Springfield, IL", "Springfield, MO"]) is None


def test_education_and_degree_families():
    from app.automation.field_matcher import degree_family

    facts = ApplicantFacts(
        school="San Jose State University", degree="B.S.", discipline="Computer Science",
        grad_year="2022", grad_month="August",
    )  # fmt: skip
    assert plan_field(field("School", "combobox"), facts).value == "San Jose State University"
    degree = field("Degree", "select", options=("Associate's Degree", "Bachelor's Degree",
                                                "Master's Degree"))  # fmt: skip
    assert plan_field(degree, facts).value == "Bachelor's Degree"
    assert plan_field(field("Discipline"), facts).value == "Computer Science"
    month = field("End date month", "select", options=("Jul", "Aug", "Sep"))
    assert plan_field(month, facts).value == "Aug"
    assert plan_field(field("End date year"), facts).value == "2022"
    assert [degree_family(d) for d in ("M.Sc", "PhD", "Bachelor of Arts", "MBA")] == [
        "Master", "Doctor", "Bachelor", "Master",
    ]  # fmt: skip


def test_year_ranges_and_long_questions():
    menu = field("How many years of relevant work experience do you have?", "select",
                 options=("0-2 years", "3-5 years", "6-9 years", "10+ years"))  # fmt: skip
    assert plan_field(menu, FACTS).value == "6-9 years"  # 6 years
    # "employer" inside a long yes/no question does not mean "your employer's name".
    agreements = field("Are you subject to any employment agreements or post-employment "
                       "restrictions with your current employer?", "radio",
                       options=("Yes", "No"), required=True)  # fmt: skip
    assert plan_field(agreements, FACTS).status == "needs_you"
    assert plan_field(field("Alternative Email"), FACTS).status == "skipped"


def test_yes_no_questions_never_take_a_place_or_contact_fact():
    office = field(
        "This role requires working from an office four days per week. Are you willing "
        "to work from one of our office locations?", "combobox", required=True,
    )  # fmt: skip
    assert plan_field(office, FACTS).status == "needs_you"
    based = field("Are you currently based in Bangalore?", "radio", options=("Yes", "No"))
    assert plan_field(based, FACTS).status == "skipped"
    where = field("Where do you plan on working from (for payroll tax purposes)?", "combobox")
    assert plan_field(where, FACTS).value == "San Francisco, CA"
    assert concept_of(field("Please choose the country in which you are located.")) == "country"
