"""Live checks against the real public job-board APIs (opt-in).

    pytest -m live tests/live

Deselected by default (no network in CI). Each test fetches one board from
the suggestions directory and checks that the connector still understands
the platform's current response.
"""

import pytest

from app.connectors.http import HttpFetcher
from app.connectors.registry import build_connectors

pytestmark = pytest.mark.live

BOARDS = [("greenhouse", "figma"), ("lever", "spotify"), ("ashby", "ramp")]


@pytest.mark.parametrize(("source", "slug"), BOARDS)
async def test_live_board_normalizes(source, slug):
    http = HttpFetcher()
    try:
        connector = build_connectors(http)[source]
        health = await connector.health_check(slug)
        assert health.ok, health.error
        fetched = await connector.discover_jobs(slug)
        valid, invalid = connector.normalize_all(fetched)
    finally:
        await http.aclose()
    assert fetched.raw_jobs, f"{source}/{slug} returned no postings"
    assert len(valid) >= 0.9 * len(fetched.raw_jobs), invalid[:3]
    job = valid[0]
    assert job.title and job.url.startswith("https://") and job.description
    assert sum(bool(j.requirements) for j in valid) >= 0.5 * len(valid)
