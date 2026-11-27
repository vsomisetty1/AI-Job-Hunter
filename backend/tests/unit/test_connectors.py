"""Connectors against realistic board payloads (fixtures mirror the live APIs).

HTTP is mocked with respx; retries use an instant fake sleep.
"""

import json
from pathlib import Path

import httpx
import pytest
import respx

from app.connectors import lever as lever_module
from app.connectors.ashby import AshbyConnector
from app.connectors.greenhouse import GreenhouseConnector
from app.connectors.http import (
    BoardNotFoundError,
    ConnectorError,
    HttpFetcher,
    RetryPolicy,
    TemporaryConnectorError,
)
from app.connectors.lever import LeverConnector
from app.connectors.normalize import (
    extract_requirements,
    html_to_text,
    infer_remote_type,
    normalize_employment_type,
    parse_datetime,
    parse_salary_text,
)
from app.connectors.registry import (
    CONNECTORS,
    SOURCES,
    UnknownSourceError,
    build_connectors,
    get_connector,
)

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "boards"
GH = "https://boards-api.greenhouse.io/v1/boards"
LV = "https://api.lever.co/v0/postings"
LV_EU = "https://api.eu.lever.co/v0/postings"
AB = "https://api.ashbyhq.com/posting-api/job-board"


def load(name: str):
    return json.loads((FIX / name).read_text())


class Sleeps:
    def __init__(self) -> None:
        self.calls: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


@pytest.fixture()
def sleeps() -> Sleeps:
    return Sleeps()


@pytest.fixture()
def http(sleeps):
    return HttpFetcher(retry=RetryPolicy(attempts=3, base_delay=1, max_delay=4), sleep=sleeps)


# ------------------------------------------------------------- Greenhouse
@respx.mock
async def test_greenhouse_discovery_and_normalization(http):
    respx.get(f"{GH}/acme").mock(
        return_value=httpx.Response(200, json=load("greenhouse_board.json"))
    )
    jobs_route = respx.get(f"{GH}/acme/jobs").mock(
        return_value=httpx.Response(200, json=load("greenhouse_jobs.json"))
    )
    c = GreenhouseConnector(http)
    fetched = await c.discover_jobs("acme")
    assert jobs_route.calls.last.request.url.params["pay_transparency"] == "true"
    assert fetched.info.name == "Acme Robotics" and fetched.expected_total == 4
    valid, invalid = c.normalize_all(fetched)
    assert [j.source_job_id for j in valid] == ["4001", "4002", "4003"]
    assert invalid == [("4004", ["missing title", "missing or non-http URL"])]

    senior, analyst, intern = valid
    assert (senior.salary_min, senior.salary_max, senior.salary_currency) == (180000, 220000, "USD")
    assert "Canada Annual Base CAD 200,000 - CAD 240,000" in senior.compensation_text
    assert senior.requirements == [
        "5+ years building backend services",
        "Experience with PostgreSQL & Kafka",
    ]
    assert (
        "<" not in senior.description and "alert(1)" not in senior.description
    )  # no HTML, no script
    assert "• Design APIs in Python" in senior.description
    assert senior.posted_at.isoformat() == "2026-11-01T10:00:00-04:00"
    assert senior.raw["departments"] == ["Engineering"] and "content" not in senior.raw
    assert (analyst.remote_type, analyst.salary_min, analyst.salary_max) == (
        "remote",
        95000,
        120000,
    )
    assert analyst.posted_at.isoformat().startswith("2026-11-18")  # falls back to updated_at
    assert (intern.remote_type, intern.employment_type) == ("hybrid", "internship")


@respx.mock
async def test_greenhouse_truncated_board_is_noted(http):
    data = load("greenhouse_jobs.json") | {"meta": {"total": 50}}
    respx.get(f"{GH}/acme").mock(return_value=httpx.Response(200, json={"name": "Acme"}))
    respx.get(f"{GH}/acme/jobs").mock(return_value=httpx.Response(200, json=data))
    fetched = await GreenhouseConnector(http).discover_jobs("acme")
    assert fetched.notes == ["board reports 50 jobs but returned 4"]


# ------------------------------------------------------------------ Lever
@respx.mock
async def test_lever_paginates_until_short_page(http, monkeypatch):
    monkeypatch.setattr(lever_module, "PAGE_SIZE", 2)
    postings = load("lever_postings.json")
    route = respx.get(f"{LV}/acme").mock(
        side_effect=lambda req: httpx.Response(
            200, json=postings[int(req.url.params["skip"]) : int(req.url.params["skip"]) + 2]
        )
    )
    c = LeverConnector(http)
    fetched = await c.discover_jobs("acme")
    assert fetched.pages == 3 and len(fetched.raw_jobs) == 5
    assert [int(call.request.url.params["skip"]) for call in route.calls] == [0, 2, 4]
    assert fetched.info.name == "Acme"

    valid, invalid = c.normalize_all(fetched)
    assert not invalid
    frontend, sre, contract, warehouse, manager = valid
    assert (frontend.remote_type, frontend.employment_type) == ("remote", "full_time")
    assert (frontend.salary_min, frontend.salary_max) == (120000, 150000)  # from text
    assert frontend.requirements == ["You have 1+ years of experience", "You like TypeScript"]
    assert "Who You Are" in frontend.description
    assert (sre.salary_min, sre.salary_max, sre.salary_currency) == (140000, 170000, "USD")
    assert sre.employment_type == "full_time" and sre.remote_type == "hybrid"
    assert contract.salary_min is None and "per-hour-wage" in contract.compensation_text
    assert contract.employment_type == "contract" and contract.remote_type == "onsite"
    assert warehouse.employment_type == "temporary"
    assert manager.employment_type is None
    assert frontend.apply_url.endswith("/apply") and frontend.posted_at.year == 2026


@respx.mock
async def test_lever_stops_if_skip_is_ignored(http, monkeypatch):
    monkeypatch.setattr(lever_module, "PAGE_SIZE", 2)
    page = load("lever_postings.json")[:2]
    route = respx.get(f"{LV}/acme").mock(return_value=httpx.Response(200, json=page))
    fetched = await LeverConnector(http).discover_jobs("acme")
    assert len(fetched.raw_jobs) == 2 and route.call_count == 2  # no infinite loop


@respx.mock
async def test_lever_eu_region_fallback(http):
    respx.get(f"{LV}/acme-eu").mock(return_value=httpx.Response(404, json={"ok": False}))
    respx.get(f"{LV_EU}/acme-eu").mock(
        return_value=httpx.Response(200, json=load("lever_postings.json")[:1])
    )
    fetched = await LeverConnector(http).discover_jobs("acme-eu")
    assert len(fetched.raw_jobs) == 1 and fetched.notes == ["region https://api.eu.lever.co"]


@respx.mock
async def test_lever_unknown_board(http):
    respx.get(f"{LV}/nope").mock(return_value=httpx.Response(404))
    respx.get(f"{LV_EU}/nope").mock(return_value=httpx.Response(404))
    with pytest.raises(BoardNotFoundError):
        await LeverConnector(http).discover_jobs("nope")


# ------------------------------------------------------------------ Ashby
@respx.mock
async def test_ashby_discovery_and_normalization(http):
    route = respx.get(f"{AB}/acme").mock(
        return_value=httpx.Response(200, json=load("ashby_board.json"))
    )
    c = AshbyConnector(http)
    fetched = await c.discover_jobs("acme")
    assert route.calls.last.request.url.params["includeCompensation"] == "true"
    assert len(fetched.raw_jobs) == 2 and fetched.notes == ["1 unlisted postings ignored"]
    (ml, intern), invalid = c.normalize_all(fetched)
    assert not invalid
    assert ml.title == "Machine Learning Engineer"  # whitespace cleaned
    assert ml.location == "New York, NY (HQ); Remote (US)"
    assert (ml.remote_type, ml.employment_type) == ("hybrid", "full_time")
    assert (ml.salary_min, ml.salary_max, ml.salary_currency) == (211400, 290600, "USD")
    assert ml.requirements == ["3+ years of PyTorch", "Strong statistics", "Robotics experience"]
    assert (intern.employment_type, intern.remote_type) == ("internship", "remote")
    assert intern.salary_min is None  # hourly pay is not an annual salary
    assert intern.apply_url is None


# ------------------------------------------------------ HTTP behaviour
@respx.mock
async def test_retry_after_honoured_then_success(http, sleeps):
    respx.get(f"{AB}/acme").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "2"}),
            httpx.Response(503),
            httpx.Response(200, json=load("ashby_board.json")),
        ]
    )
    fetched = await AshbyConnector(http).discover_jobs("acme")
    assert len(fetched.raw_jobs) == 2
    assert sleeps.calls[0] == 2.0 and 1.0 <= sleeps.calls[1] * 2 <= 4.0  # Retry-After, then backoff


@respx.mock
async def test_gives_up_after_retries(http, sleeps):
    route = respx.get(f"{AB}/acme").mock(return_value=httpx.Response(500))
    with pytest.raises(TemporaryConnectorError):
        await AshbyConnector(http).discover_jobs("acme")
    assert route.call_count == 3 and len(sleeps.calls) == 2


@respx.mock
async def test_timeouts_are_retried(http):
    respx.get(f"{AB}/acme").mock(
        side_effect=[httpx.ReadTimeout("slow"), httpx.Response(200, json=load("ashby_board.json"))]
    )
    assert len((await AshbyConnector(http).discover_jobs("acme")).raw_jobs) == 2


@pytest.mark.parametrize(
    ("response", "error"),
    [
        (httpx.Response(403), ConnectorError),
        (httpx.Response(200, content=b"<html>not json</html>"), ConnectorError),
        (httpx.Response(200, json={"unexpected": True}), ConnectorError),
        (httpx.Response(404), BoardNotFoundError),
    ],
)
@respx.mock
async def test_non_retryable_failures(http, sleeps, response, error):
    respx.get(f"{AB}/acme").mock(return_value=response)
    with pytest.raises(error):
        await AshbyConnector(http).discover_jobs("acme")
    assert sleeps.calls == []


@respx.mock
async def test_oversized_response_is_refused(sleeps):
    small = HttpFetcher(max_bytes=1000, sleep=sleeps)
    respx.get(f"{AB}/acme").mock(return_value=httpx.Response(200, content=b"x" * 5000))
    with pytest.raises(ConnectorError, match="too large"):
        await AshbyConnector(small).discover_jobs("acme")


@respx.mock
async def test_health_check(http):
    respx.get(f"{AB}/ashby").mock(return_value=httpx.Response(200, json=load("ashby_board.json")))
    respx.get(f"{AB}/gone").mock(return_value=httpx.Response(404))
    c = AshbyConnector(http)
    ok = await c.health_check()
    assert ok.ok and ok.board == "ashby" and ok.jobs_visible == 2
    bad = await c.health_check("gone")
    assert not bad.ok and bad.error == "board not found"


async def test_registry(http):
    assert SOURCES == ("greenhouse", "lever", "ashby")
    connectors = build_connectors(http)
    assert {type(c) for c in connectors.values()} == set(CONNECTORS.values())
    assert get_connector(connectors, "lever").display_name == "Lever"
    with pytest.raises(UnknownSourceError):
        get_connector(connectors, "workday")


# ----------------------------------------------------------- helpers
def test_html_to_text_and_requirements():
    markup = (
        "<h2>About</h2><p>We build&nbsp;things.<br>Fast.</p><style>p{}</style>"
        "<p><strong>Requirements</strong></p>"
        "<ul><li><p>Python</p></li><li>SQL <b>and</b> dbt</li></ul>"
        "<h3>Benefits</h3><ul><li>Health</li></ul>"
    )
    text = html_to_text(markup)
    assert text == (
        "About\n\nWe build\u00a0things.\nFast.\n\nRequirements\n\n"
        "\u2022 Python\n\n\u2022 SQL and dbt\n\nBenefits\n\n\u2022 Health"
    )
    assert extract_requirements(markup) == ["Python", "SQL and dbt"]
    assert html_to_text("&lt;p&gt;Hi &amp;amp; bye&lt;/p&gt;", escaped=True) == "Hi & bye"
    assert html_to_text(None) == ""


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("The base salary range is $95,000 - $120,000.", (95000, 120000, "USD")),
        ("Compensation: €50.000 – €65.000 per year", (50000, 65000, "EUR")),
        ("OTE range USD 120K to 150K", (120000, 150000, "USD")),
        ("Pay range: $25 - $30 per hour", (None, None, None)),
        ("We raised $100,000 - $200,000 last year", (None, None, None)),
        ("", (None, None, None)),
    ],
)
def test_salary_text(text, expected):
    s = parse_salary_text(text)
    assert (s.min, s.max, s.currency) == expected


@pytest.mark.parametrize(
    ("workplace", "location", "is_remote", "expected"),
    [
        ("OnSite", None, None, "onsite"),
        ("Hybrid", "Remote (US)", True, "hybrid"),
        (None, "Remote - Europe", None, "remote"),
        (None, "Hybrid - Boston", None, "hybrid"),
        (None, "Berlin, Germany", None, "unknown"),
        (None, "Berlin", True, "remote"),
    ],
)
def test_remote_type(workplace, location, is_remote, expected):
    assert infer_remote_type(workplace, location, is_remote=is_remote) == expected


def test_employment_type_and_dates():
    assert normalize_employment_type("FullTime") == "full_time"
    assert normalize_employment_type("Part-time") == "part_time"
    assert normalize_employment_type(None, "Data Science Intern") == "internship"
    assert normalize_employment_type("Something else") is None
    assert parse_datetime(0).year == 1970
    assert parse_datetime("2026-01-02T03:04:05Z").tzinfo is not None
    assert parse_datetime("not a date") is None
