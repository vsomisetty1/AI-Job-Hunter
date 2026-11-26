"""Static checks on backend/schema.sql (no database needed)."""
from collections import Counter

from tests.unit.schema_parser import parse_index_names, parse_tables

REQUIRED_TABLES = {
    "candidate_profiles",
    "resumes",
    "resume_versions",
    "jobs",
    "job_scores",
    "applications",
    "application_answers",
    "cover_letters",
    "agent_runs",
    "settings",
    "browser_sessions",
}


def test_all_required_tables_present(schema_sql):
    tables = set(parse_tables(schema_sql))
    assert REQUIRED_TABLES <= tables
    assert "llm_cache" in tables  # Redis replacement


def test_no_percent_character(schema_sql):
    # The migration runs the file through the raw driver, where % is special.
    assert "%" not in schema_sql


def test_foreign_keys_reference_earlier_tables(schema_sql):
    seen: set[str] = set()
    for name, table in parse_tables(schema_sql).items():
        for ref in table.references:
            assert ref in seen, f"{name} references {ref} before it is created"
        seen.add(name)


def test_constraint_and_index_names_unique(schema_sql):
    tables = parse_tables(schema_sql)
    names = [c for t in tables.values() for c in t.constraints] + parse_index_names(schema_sql)
    dupes = [n for n, c in Counter(names).items() if c > 1]
    assert not dupes, dupes


def test_every_table_has_a_primary_key(schema_sql):
    for name in parse_tables(schema_sql):
        assert f"CREATE TABLE {name}" in schema_sql
    assert schema_sql.count("PRIMARY KEY") >= len(parse_tables(schema_sql))


def test_status_values_cover_tracking_stages(schema_sql):
    for stage in ("drafted", "ready", "submitted", "interview", "rejected", "offer"):
        assert f"'{stage}'" in schema_sql
    assert "'APPROVAL_MODE'" in schema_sql and "'AUTONOMOUS_MODE'" in schema_sql
