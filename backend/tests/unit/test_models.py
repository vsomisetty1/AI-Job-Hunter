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
