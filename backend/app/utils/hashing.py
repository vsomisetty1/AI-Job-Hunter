"""Hashing helpers.

All digests are lowercase hex SHA-256, matching the `^[0-9a-f]{64}$` CHECK
constraints in schema.sql.
"""

import hashlib
import json
from typing import Any

from app.utils.text import normalize_whitespace


def sha256_hex(data: str | bytes) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def stable_json(value: Any) -> str:
    """Deterministic JSON (sorted keys, no spaces) for hashing structured input."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def hash_json(value: Any) -> str:
    return sha256_hex(stable_json(value))


def hash_question(question: str) -> str:
    """Key for application questions: case- and whitespace-insensitive."""
    return sha256_hex(normalize_whitespace(question).casefold())


def hash_file(data: bytes) -> str:
    return sha256_hex(data)
