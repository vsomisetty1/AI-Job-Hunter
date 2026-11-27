import re

import pytest

from app.utils.hashing import hash_json, hash_question, sha256_hex, stable_json
from app.utils.text import normalize_whitespace, slugify, strip_html, truncate

HEX64 = re.compile(r"^[0-9a-f]{64}$")


def test_sha256_matches_schema_check():
    assert HEX64.match(sha256_hex("x"))
    assert sha256_hex("x") == sha256_hex(b"x")


def test_stable_json_ignores_key_order():
    assert stable_json({"b": 1, "a": [1, 2]}) == stable_json({"a": [1, 2], "b": 1})
    assert hash_json({"b": 1, "a": 2}) == hash_json({"a": 2, "b": 1})


def test_question_hash_is_case_and_space_insensitive():
    assert hash_question("  Are you  authorized\nto work? ") == hash_question(
        "are you authorized to work?"
    )


def test_normalize_whitespace_folds_unicode_spaces():
    assert normalize_whitespace("a  b\t\nc ") == "a b c"


@pytest.mark.parametrize(
    ("text", "slug"),
    [
        ("Senior Engineer (Backend)", "senior-engineer-backend"),
        ("Café Zürich", "cafe-zurich"),
        ("---", ""),
    ],
)
def test_slugify(text, slug):
    assert slugify(text) == slug


def test_truncate():
    assert truncate("hello world", 20) == "hello world"
    assert truncate("hello world", 8) == "hello..."
    assert len(truncate("x" * 100, 10)) == 10
    with pytest.raises(ValueError):
        truncate("abc", 2)


def test_strip_html():
    assert strip_html("<p>Hello <b>there</b></p><br/>World") == "Hello there World"
