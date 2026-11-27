"""Unit: Agent 3 deduplication (fingerprints, content hashes, decisions)."""

import uuid

from app.agents.agent_3_deduplication import (
    Existing,
    content_hash,
    decide,
    dedup_key,
    normalize_company,
    normalize_location,
    normalize_title,
)
from app.schemas.job import NormalizedJob


def job(ext="1", title="Senior Engineer", url=None, company="Acme Robotics", **kw):
    return NormalizedJob(
        source="greenhouse",
        source_job_id=ext,
        company_name=company,
        title=title,
        url=url or f"https://acme.example/jobs/{ext}",
        **kw,
    )


def test_normalizers_fold_case_accents_aliases_and_suffixes():
    assert normalize_company("Acme Robotics, Inc.") == normalize_company("acme robotics")
    assert normalize_company("Café Labs GmbH") == "cafe"
    assert normalize_title("Sr. Software Eng (Remote)") == "senior software engineer"
    assert normalize_title("R&D Lead") == "r and d lead"
    assert normalize_location("New York, NY; San Francisco, CA") == normalize_location(
        "san francisco ca; new york ny"
    )


def test_dedup_key_matches_same_job_across_spellings():
    a = dedup_key("Acme Robotics Inc", "Sr. Backend Engineer", "Remote - US")
    b = dedup_key("ACME Robotics", "Senior Backend Engineer", "remote, us")
    assert a == b and len(a) == 64
    assert a != dedup_key("Acme Robotics", "Senior Backend Engineer", "Austin, TX")


def test_content_hash_ignores_raw_but_tracks_visible_fields():
    base = job(description="x")
    assert content_hash(base) == content_hash(job(description="x", raw={"anything": 1}))
    assert content_hash(base) != content_hash(job(description="y"))


def test_decide_insert_unchanged_update_and_revive():
    same, changed, expired = job("1"), job("2", description="new"), job("3")
    existing = {
        "1": Existing(uuid.uuid4(), content_hash(same), "new"),
        "2": Existing(uuid.uuid4(), content_hash(job("2", description="old")), "new"),
        "3": Existing(uuid.uuid4(), content_hash(expired), "expired"),
    }
    out = decide([same, changed, expired, job("4")], existing=existing, url_owners={},
                 fingerprint_owners={})  # fmt: skip
    assert [d.action for d in out] == ["unchanged", "update", "update", "insert"]
    assert out[2].revive and not out[1].revive
    assert out[0].existing_id == existing["1"].id


def test_decide_skips_repeats_and_url_collisions():
    other = uuid.uuid4()
    jobs = [
        job("1"),
        job("1"),  # same id twice in one response
        job("2", url="https://acme.example/jobs/1"),  # same URL, different id
        job("3", url="https://taken.example/x"),
    ]
    out = decide(jobs, existing={}, url_owners={"https://taken.example/x": (other, "zz")},
                 fingerprint_owners={})  # fmt: skip
    assert [d.action for d in out] == ["insert", "skip", "skip", "skip"]
    assert [d.reason for d in out[1:]] == [
        "repeated in the board response",
        "URL repeated in the board response",
        "URL already belongs to another job",
    ]
    assert out[3].existing_id == other


def test_own_url_is_not_a_collision():
    mine = uuid.uuid4()
    j = job("1")
    out = decide([j], existing={"1": Existing(mine, content_hash(j), "new")},
                 url_owners={j.url: (mine, "1")}, fingerprint_owners={})  # fmt: skip
    assert out[0].action == "unchanged"


def test_cross_board_fingerprint_skip_but_same_company_repeats_kept():
    twin = uuid.uuid4()
    a = job("1", title="Data Analyst", location="Remote - US")
    b = job("2", title="Data Analyst", location="Remote - US")
    key = dedup_key(a.company_name, a.title, a.location)
    # Same title twice on one board: both are real openings (no fingerprint owner).
    assert [d.action for d in decide([a, b], existing={}, url_owners={},
                                     fingerprint_owners={})] == ["insert", "insert"]  # fmt: skip
    # Already stored for another company row (same employer on another platform).
    out = decide([a], existing={}, url_owners={}, fingerprint_owners={key: twin})
    assert (out[0].action, out[0].existing_id) == ("skip", twin)
    assert out[0].reason == "same job already found on another board"
