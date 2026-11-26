"""Static validation of backend/schema.sql (no database needed)."""
import re
from collections import Counter

from tests.conftest import BACKEND_DIR
from tests.unit.schema_parser import parse_indexes, parse_tables, parse_triggers

REQUIRED_TABLES = {
    "candidate_profiles", "resumes", "resume_versions", "jobs", "job_scores",
    "applications", "application_answers", "cover_letters", "agent_runs",
    "settings", "browser_sessions",
}  # fmt: skip
# Tables intentionally without created_at / updated_at.
NO_CREATED_AT = {"agent_runs"}  # uses started_at
IMMUTABLE = {  # append-only rows: no updated_at, so no trigger needed
    "job_scores", "application_events", "agent_runs", "llm_cache_entries",
}  # fmt: skip


def test_required_tables_present(schema_sql):
    tables = set(parse_tables(schema_sql))
    assert REQUIRED_TABLES <= tables
    assert {"companies", "application_events", "llm_cache_entries"} <= tables


def test_no_duplicate_tables_or_old_names(schema_sql):
    names = [m for m in __import__("re").findall(r"CREATE TABLE (\w+)", schema_sql)]
    assert len(names) == len(set(names))
    assert "llm_cache" not in names  # renamed to llm_cache_entries


def test_no_char_n_columns(schema_sql):
    # char(n) comparisons against text/varchar parameters bypass indexes.
    assert not re.search(r"\bchar\(\d+\)", schema_sql, re.I)


def test_no_percent_character(schema_sql):
    assert "%" not in schema_sql  # raw driver treats % specially


def test_foreign_keys_reference_earlier_tables(schema_sql):
    seen = set()
    for name, table in parse_tables(schema_sql).items():
        for ref in table.references:
            assert ref in seen, f"{name} references {ref} before it is created"
        seen.add(name)


def test_all_foreign_keys_are_named_table_level(schema_sql):
    for name, table in parse_tables(schema_sql).items():
        fk_names = [c for c in table.constraints if c.startswith("fk_")]
        assert len(fk_names) == len(table.references), f"{name}: unnamed/inline FK"
        for c in fk_names:
            assert c.startswith(f"fk_{name}_"), c


def test_every_fk_is_backed_by_an_index(schema_sql):
    """FK columns need a leading-column index (fast joins and cascades)."""
    tables = parse_tables(schema_sql)
    indexes = parse_indexes(schema_sql)
    for name, table in tables.items():
        leads = {u[0] for u in table.unique_sets if u} | {
            i.columns[0] for i in indexes if i.table == name and i.columns
        }
        for col in table.fk_lead_columns:
            assert col in leads, f"{name}.{col} has no index"


def test_no_redundant_indexes(schema_sql):
    """A plain index that is a column-prefix of another index/unique is waste."""
    tables = parse_tables(schema_sql)
    indexes = parse_indexes(schema_sql)
    for ix in indexes:
        if ix.partial or None in ix.columns:
            continue
        covering = [u for u in tables[ix.table].unique_sets]
        covering += [
            o.columns for o in indexes if o is not ix and o.table == ix.table and not o.partial
        ]
        for other in covering:
            assert not (
                None not in other and other[: len(ix.columns)] == ix.columns
            ), f"{ix.name} is redundant with {other}"


def test_constraint_and_index_names_unique_and_prefixed(schema_sql):
    tables = parse_tables(schema_sql)
    indexes = parse_indexes(schema_sql)
    names = [c for t in tables.values() for c in t.constraints] + [i.name for i in indexes]
    assert not [n for n, c in Counter(names).items() if c > 1]
    for t in tables.values():
        for c in t.constraints:
            assert c.startswith(("ck_", "uq_", "fk_")), c
    for i in indexes:
        assert i.name.startswith("uq_" if i.unique else "ix_"), i.name


def test_audit_fields_and_updated_at_triggers(schema_sql):
    tables = parse_tables(schema_sql)
    triggers = parse_triggers(schema_sql)
    for name, t in tables.items():
        if name not in NO_CREATED_AT:
            assert "created_at" in t.columns, f"{name} lacks created_at"
        if "updated_at" in t.columns:
            assert name in triggers, f"{name} has updated_at but no trigger"
        else:
            assert name in IMMUTABLE, f"{name} is mutable but has no updated_at"


def test_every_jsonb_column_is_type_checked(schema_sql):
    for name, t in parse_tables(schema_sql).items():
        body = re.search(rf"CREATE TABLE {name} \((.*?)\n\);", schema_sql, re.S).group(1)
        for col in re.findall(r"^\s{4}(\w+)\s+jsonb\b", body, re.M):
            if name == "llm_cache_entries" and col == "response":
                continue  # arbitrary model output
            assert f"jsonb_typeof({col})" in body, f"{name}.{col} lacks a jsonb_typeof check"


def test_status_values_cover_tracking_stages(schema_sql):
    for stage in ("drafted", "ready", "submitted", "interview", "rejected", "offer"):
        assert f"'{stage}'" in schema_sql
    assert "'APPROVAL_MODE'" in schema_sql and "'AUTONOMOUS_MODE'" in schema_sql


def test_reference_schema_matches_frozen_migration_sql():
    """Until revision 0002 exists, schema.sql == migration 0001 SQL.

    Once a second revision is added, replace this with a check against a
    database migrated to head (see integration/test_migrations.py).
    """
    versions = list((BACKEND_DIR / "migrations" / "versions").glob("0*.py"))
    if len(versions) != 1:
        return
    frozen = (BACKEND_DIR / "migrations" / "sql" / "0001_initial.sql").read_text()
    assert frozen == (BACKEND_DIR / "schema.sql").read_text()
