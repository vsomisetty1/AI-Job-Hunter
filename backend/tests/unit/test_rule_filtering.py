"""Unit: Agent 4 rule filtering (pure functions, no database)."""

import dataclasses

import pytest

from app.agents.agent_4_rule_filtering import (
    RULES,
    RULES_VERSION,
    FilterJob,
    FilterPreferences,
    check_company,
    check_duplicate,
    check_employment_type,
    check_keywords,
    check_location,
    check_remote,
    check_salary,
    check_sponsorship,
    contains_term,
    evaluate,
    fingerprint,
    fold,
    is_generic_remote,
    matches_location,
    us_states_in,
)


def job(**kw) -> FilterJob:
    base = {"title": "Senior Backend Engineer", "company_name": "Acme Robotics"}
    return FilterJob(**(base | kw))


def prefs(**kw) -> FilterPreferences:
    return FilterPreferences(**kw)


# ------------------------------------------------------------------ helpers
def test_fold_and_whole_word_matching():
    assert fold("  Zürich   Office ") == "zurich office"
    assert contains_term("we use c++ daily", "c++")
    assert not contains_term("javascript", "java")  # whole words only
    assert contains_term("remote - u.s.", "u.s.")
    assert not contains_term("anything", "")


@pytest.mark.parametrize(
    ("location", "preference", "expected"),
    [
        ("San Francisco, CA", "San Francisco", True),
        ("San Francisco, CA", "SF", True),  # alias group
        ("New York, NY", "NYC", True),
        ("Austin, TX", "United States", True),  # a US state counts as the US
        ("Austin, TX", "Texas", True),
        ("Austin, TX", "tx", True),
        ("Remote - US", "USA", True),
        ("London, UK", "United Kingdom", True),
        ("Berlin, Germany", "Europe", False),  # no country table: not guessed
        ("Seattle, WA", "New York", False),
        ("Washington, DC", "Washington DC", True),
        ("Toronto, ON", "United States", False),  # ON is not a US state
    ],
)
def test_matches_location(location, preference, expected):
    assert matches_location(location, preference) is expected


def test_us_states_detection():
    assert us_states_in("Austin, TX; Denver, CO") == {"TX", "CO"}
    assert us_states_in("Remote (NY)") == {"NY"}
    assert us_states_in("Remote - Texas") == {"TX"}
    assert us_states_in("Washington, DC") == {"DC"}  # not Washington state
    assert us_states_in("Seattle, Washington State") == {"WA"}
    assert us_states_in("Hamburg, Germany") == set()


@pytest.mark.parametrize(
    ("location", "generic"),
    [(None, True), ("Remote", True), ("Remote - Worldwide", True), ("Anywhere", True),
     ("Remote - US", False), ("Remote, Europe", False)],
)  # fmt: skip
def test_generic_remote(location, generic):
    assert is_generic_remote(location) is generic


# -------------------------------------------------------------------- rules
def test_duplicate_rule():
    assert check_duplicate(job(), prefs()).passed
    failed = check_duplicate(job(duplicate_of="b1f6..."), prefs())
    assert not failed.passed and "another board" in failed.reason


def test_company_rule_matches_whole_words_case_insensitively():
    p = prefs(excluded_companies=("acme",))
    assert not check_company(job(company_name="ACME Robotics"), p).passed
    assert check_company(job(company_name="Acmeville Labs"), p).passed
    assert check_company(job(), prefs()).passed


def test_keyword_rule_reports_where_it_matched():
    p = prefs(excluded_keywords=("clearance", "PHP"))
    hit = check_keywords(job(requirements=("Active security clearance",)), p)
    assert not hit.passed and hit.reason == "Excluded keyword 'clearance' in the requirements"
    assert "title" in check_keywords(job(title="PHP Developer"), p).reason
    assert "description" in check_keywords(job(description="Our stack is PHP."), p).reason
    assert check_keywords(job(description="graphics and phpunit"), p).passed  # whole words
    assert check_keywords(job(), prefs()).reason == "No excluded keywords set"


class TestLocation:
    def test_no_preference_passes(self):
        assert check_location(job(location="Tokyo"), prefs()).passed

    def test_matching_and_non_matching(self):
        p = prefs(preferred_locations=("New York", "Austin"))
        assert check_location(job(location="Austin, TX"), p).reason == "Location matches 'Austin'"
        r = check_location(job(location="Seattle, WA", remote_type="onsite"), p)
        assert not r.passed and "Seattle" in r.reason

    def test_missing_location_never_rejects(self):
        p = prefs(preferred_locations=("New York",))
        assert check_location(job(location=None), p).reason == "Location not listed"

    def test_remote_jobs(self):
        p = prefs(preferred_locations=("New York",))
        # Open to anyone: fine for a New Yorker.
        assert check_location(job(location="Remote", remote_type="remote"), p).passed
        assert check_location(job(location=None, remote_type="remote"), p).passed
        # Remote but restricted to a region elsewhere: rejected.
        assert not check_location(job(location="Remote - Europe", remote_type="remote"), p).passed
        # Remote within the US, for a US preference: kept.
        us = prefs(preferred_locations=("United States",))
        assert check_location(job(location="Remote - US", remote_type="remote"), us).passed

    def test_remote_as_a_preferred_location_accepts_any_remote_job(self):
        p = prefs(preferred_locations=("Remote", "Berlin"))
        assert check_location(job(location="Remote - Brazil", remote_type="remote"), p).passed
        assert not check_location(job(location="Paris", remote_type="onsite"), p).passed

    def test_onsite_preference_does_not_use_the_remote_shortcut(self):
        p = prefs(preferred_locations=("Remote",), remote_preference="onsite")
        assert not check_location(job(location="Remote - Brazil", remote_type="remote"), p).passed


@pytest.mark.parametrize(
    ("preference", "workplace", "passed"),
    [
        ("any", "onsite", True),
        ("remote_only", "remote", True),
        ("remote_only", "hybrid", False),
        ("remote_only", "unknown", True),  # not stated: kept
        ("hybrid", "remote", True),
        ("hybrid", "onsite", False),
        ("onsite", "hybrid", True),
        ("onsite", "remote", False),
    ],
)
def test_remote_rule(preference, workplace, passed):
    assert check_remote(job(remote_type=workplace), prefs(remote_preference=preference)).passed is (
        passed
    )


def test_remote_rule_reason():
    r = check_remote(job(remote_type="onsite"), prefs(remote_preference="remote_only"))
    assert r.reason == "Onsite job, but you want remote only work"


def test_employment_type_rule():
    p = prefs(job_types=("full_time", "contract"))
    assert check_employment_type(job(employment_type="contract"), p).passed
    r = check_employment_type(job(employment_type="internship"), p)
    assert not r.passed and r.reason == "Internship is not a wanted employment type"
    assert (
        check_employment_type(job(employment_type=None), p).reason == "Employment type not stated"
    )
    assert check_employment_type(job(employment_type="part_time"), prefs()).passed


class TestSalary:
    def test_compares_the_top_of_the_range(self):
        p = prefs(salary_min=150_000)
        assert check_salary(job(salary_min=120_000, salary_max=160_000), p).passed
        r = check_salary(job(salary_min=100_000, salary_max=140_000), p)
        assert not r.passed
        assert r.reason == "Pays up to USD 140,000, below your minimum of USD 150,000"
        assert not check_salary(job(salary_min=140_000), p).passed  # only a minimum posted

    def test_unknown_or_other_currency_passes(self):
        p = prefs(salary_min=150_000)
        assert check_salary(job(), p).reason == "Salary not listed"
        eur = check_salary(job(salary_max=90_000, salary_currency="EUR"), p)
        assert eur.passed and eur.reason == "Salary in EUR, not compared"

    def test_no_minimum(self):
        assert check_salary(job(salary_max=10), prefs()).passed


class TestSponsorship:
    p = prefs(requires_sponsorship=True)

    @pytest.mark.parametrize(
        "text",
        [
            "We are unable to sponsor visas for this role.",
            "Candidates must be authorized to work in the US without sponsorship.",
            "Applicants must work without the need for current or future visa sponsorship.",
            "We do not offer visa sponsorship.",
            "Visa sponsorship is not available.",
            "We will not sponsor.",
            "No visa sponsorship.",
            "Must be a U.S. citizen.",
            "US citizenship is required for this position.",
        ],
    )
    def test_ruled_out(self, text):
        r = check_sponsorship(job(description=text), self.p)
        assert not r.passed and r.reason.startswith("Posting rules out sponsorship")

    def test_offered_or_silent(self):
        assert (
            check_sponsorship(job(description="Visa sponsorship is available."), self.p).reason
            == "Posting offers visa sponsorship"
        )
        assert check_sponsorship(job(description="We build robots."), self.p).passed

    def test_only_checked_when_needed(self):
        assert check_sponsorship(job(description="No visa sponsorship."), prefs()).passed

    def test_requirements_are_read_too(self):
        r = check_sponsorship(job(requirements=("Must be a US citizen",)), self.p)
        assert not r.passed


# ----------------------------------------------------------------- decision
def test_evaluate_runs_every_rule_and_collects_all_failures():
    p = prefs(
        excluded_companies=("Acme",),
        remote_preference="remote_only",
        salary_min=200_000,
    )
    d = evaluate(job(remote_type="onsite", salary_max=150_000), p)
    assert not d.passed
    assert [c.rule for c in d.checks] == [
        "duplicate", "company", "keywords", "location", "remote", "employment_type", "salary",
        "sponsorship",
    ]  # fmt: skip
    assert {c.rule for c in d.failures} == {"company", "remote", "salary"}
    assert d.reason.count(";") == 2
    data = d.as_json()
    assert data["passed"] is False and data["version"] == RULES_VERSION
    assert len(data["checks"]) == len(RULES)


def test_evaluate_passes_with_no_preferences():
    d = evaluate(job(), prefs())
    assert d.passed and d.reason is None and not d.failures


def test_fingerprint_tracks_every_input():
    j, p = job(), prefs()
    base = fingerprint(j, p)
    assert base == fingerprint(job(), prefs())  # deterministic
    assert len(base) == 64
    for field in dataclasses.fields(FilterJob):
        kind = str(field.type)
        changed = ("x",) if "tuple" in kind else 1 if "int" in kind else "x"
        assert fingerprint(dataclasses.replace(j, **{field.name: changed}), p) != base, field.name
    assert fingerprint(j, prefs(excluded_keywords=("php",))) != base
    assert fingerprint(j, prefs(requires_sponsorship=True)) != base
