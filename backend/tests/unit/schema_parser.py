"""Tiny parser for schema.sql used by tests (no SQL engine required)."""
import re
from dataclasses import dataclass, field


@dataclass
class TableDef:
    name: str
    columns: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    references: list[str] = field(default_factory=list)
    checks_without_name: int = 0


def _split_top_level(body: str) -> list[str]:
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


def _strip_comments(sql: str) -> str:
    return re.sub(r"--[^\n]*", "", sql)


def parse_tables(sql: str) -> dict[str, TableDef]:
    sql = _strip_comments(sql)
    tables: dict[str, TableDef] = {}
    for m in re.finditer(r"CREATE TABLE (\w+) \(", sql):
        start = m.end()
        depth, i = 1, start
        while depth:
            depth += {"(": 1, ")": -1}.get(sql[i], 0)
            i += 1
        body = sql[start : i - 1]
        t = TableDef(m.group(1))
        for part in _split_top_level(body):
            if part.startswith("CONSTRAINT"):
                t.constraints.append(part.split()[1])
            else:
                t.columns.append(part.split()[0])
                if re.search(r"\bCHECK\b", part):
                    t.checks_without_name += 1
            t.references += re.findall(r"REFERENCES (\w+)\(", part)
        tables[t.name] = t
    return tables


def parse_index_names(sql: str) -> list[str]:
    return re.findall(r"CREATE (?:UNIQUE )?INDEX (\w+)", _strip_comments(sql))
