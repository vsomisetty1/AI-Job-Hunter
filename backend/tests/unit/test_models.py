"""ORM models must mirror schema.sql (tables, columns, named constraints)."""
import pytest

pytest.importorskip("sqlalchemy")

from sqlalchemy import CheckConstraint, UniqueConstraint  # noqa: E402

from app.models import Base  # noqa: E402
from tests.unit.schema_parser import parse_tables  # noqa: E402


def test_tables_match_schema(schema_sql):
    assert set(Base.metadata.tables) == set(parse_tables(schema_sql))


def test_columns_match_schema(schema_sql):
    for name, sql_table in parse_tables(schema_sql).items():
        orm_cols = {c.name for c in Base.metadata.tables[name].columns}
        assert orm_cols == set(sql_table.columns), name


def test_named_constraints_match_schema(schema_sql):
    for name, sql_table in parse_tables(schema_sql).items():
        orm = {
            c.name
            for c in Base.metadata.tables[name].constraints
            if isinstance(c, (CheckConstraint, UniqueConstraint)) and c.name
        }
        sql = {c for c in sql_table.constraints if c.startswith(("ck_", "uq_"))}
        assert orm == sql, name


def test_composite_foreign_keys_guarantee_same_job():
    from sqlalchemy import ForeignKeyConstraint

    apps = Base.metadata.tables["applications"]
    composite = {
        tuple(c.name for c in fk.columns): fk.ondelete
        for fk in apps.constraints
        if isinstance(fk, ForeignKeyConstraint) and len(fk.columns) == 2
    }
    assert composite == {
        ("resume_version_id", "job_id"): "SET NULL (resume_version_id)",
        ("cover_letter_id", "job_id"): "SET NULL (cover_letter_id)",
        ("job_score_id", "job_id"): "SET NULL (job_score_id)",
    }


def test_job_and_application_history_protected():
    jobs_fk = {fk.parent.name: fk.ondelete for fk in Base.metadata.tables["jobs"].foreign_keys}
    app_fk = {fk.parent.name: fk.ondelete for fk in Base.metadata.tables["applications"].foreign_keys}
    assert jobs_fk["company_id"] == "RESTRICT"
    assert app_fk["job_id"] == "RESTRICT"
