"""Tiny parser for schema.sql used by tests (no SQL engine required)."""
import re
from dataclasses import dataclass, field


@dataclass
class IndexDef:
    name: str
    table: str
    columns: tuple  # plain column names; None marks an expression
    unique: bool
    partial: bool


@dataclass
class TableDef:
    name: str
    columns: list = field(default_factory=list)
    constraints: list = field(default_factory=list)
    references: list = field(default_factory=list)
    fk_lead_columns: list = field(default_factory=list)
    unique_sets: list = field(default_factory=list)  # tuples (PK + UNIQUE constraints)
    pk: tuple = ()


def strip_comments(sql: str) -> str:
    return re.sub(r"--[^\n]*", "", sql)


def split_top_level(body: str) -> list:
    parts, depth, cur = [], 0, []
    for ch in body:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    if "".join(cur).strip():
        parts.append("".join(cur).strip())
    return parts


def _cols(text: str) -> tuple:
    out = []
    for item in split_top_level(text):
        m = re.match(r"^(\w+)(\s+(ASC|DESC))?(\s+NULLS\s+(FIRST|LAST))?$", item.strip())
        out.append(m.group(1) if m else None)
    return tuple(out)


def parse_tables(sql: str) -> dict:
    sql = strip_comments(sql)
    tables = {}
    for m in re.finditer(r"CREATE TABLE (\w+) \(", sql):
        start, depth, i = m.end(), 1, m.end()
        while depth:
            depth += {"(": 1, ")": -1}.get(sql[i], 0)
            i += 1
        t = TableDef(m.group(1))
        for part in split_top_level(sql[start : i - 1]):
            if part.startswith("CONSTRAINT"):
                t.constraints.append(part.split()[1])
                fk = re.search(r"FOREIGN KEY \((\w+)", part)
                if fk:
                    t.fk_lead_columns.append(fk.group(1))
                    t.references += re.findall(r"REFERENCES (\w+)\(", part)
                uq = re.search(r"\bUNIQUE \(([^)]*)\)", part)
                if uq:
                    t.unique_sets.append(_cols(uq.group(1)))
            else:
                col = part.split()[0]
                t.columns.append(col)
                if "PRIMARY KEY" in part:
                    t.pk = (col,)
                    t.unique_sets.append((col,))
                if "REFERENCES" in part:  # inline FKs are banned by a test
                    t.references += re.findall(r"REFERENCES (\w+)\(", part)
                    t.fk_lead_columns.append(col)
        tables[t.name] = t
    return tables


def parse_indexes(sql: str) -> list:
    sql = strip_comments(sql)
    out = []
    pattern = r"CREATE (UNIQUE )?INDEX (\w+)\s+ON (\w+) \((.*?)\)\s*(WHERE [^;]*)?;"
    for m in re.finditer(pattern, sql, re.S):
        out.append(IndexDef(m.group(2), m.group(3), _cols(m.group(4)), bool(m.group(1)), bool(m.group(5))))
    return out


def parse_triggers(sql: str) -> dict:
    """{table: trigger_name} for BEFORE UPDATE triggers."""
    return {
        m.group(2): m.group(1)
        for m in re.finditer(r"CREATE TRIGGER (\w+)\s+BEFORE UPDATE ON (\w+)", strip_comments(sql))
    }
