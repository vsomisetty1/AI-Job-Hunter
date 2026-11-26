"""Text helpers shared by parsing, normalization and dedup code."""

import re
import unicodedata

_WS = re.compile(r"\s+")
_NON_SLUG = re.compile(r"[^a-z0-9]+")
_TAG = re.compile(r"<[^>]+>")


def normalize_unicode(text: str) -> str:
    """NFKC-normalize (folds ligatures, full-width chars, non-breaking spaces)."""
    return unicodedata.normalize("NFKC", text)


def normalize_whitespace(text: str) -> str:
    return _WS.sub(" ", normalize_unicode(text)).strip()


def strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def slugify(text: str, max_length: int = 80) -> str:
    slug = _NON_SLUG.sub("-", strip_accents(normalize_unicode(text)).lower()).strip("-")
    return slug[:max_length].rstrip("-")


def truncate(text: str, max_length: int, suffix: str = "...") -> str:
    if max_length < len(suffix):
        raise ValueError("max_length must be at least len(suffix)")
    if len(text) <= max_length:
        return text
    return text[: max_length - len(suffix)].rstrip() + suffix


def strip_html(text: str) -> str:
    """Crude tag removal for job descriptions; not a sanitizer."""
    return normalize_whitespace(_TAG.sub(" ", text))
