"""Repository hygiene: no stub files left behind, docs agree on the basics.

Phase 1 created placeholder files ("PLACEHOLDER - implemented in PHASE N")
that later phases were meant to replace; Phase 10 implemented or removed the
last of them. This keeps it that way.
"""

import re

from tests.conftest import BACKEND_DIR

ROOT = BACKEND_DIR.parent
SKIP_DIRS = {
    "node_modules", ".venv", ".git", ".next", "__pycache__", ".mypy_cache", ".ruff_cache",
    "history", "data", "backups", "validation-output",
}  # fmt: skip
SUFFIXES = {".py", ".ts", ".tsx", ".mjs", ".mts", ".md", ".sh", ".yml", ".yaml", ".sql", ".toml"}
STUB = re.compile(r"PLACEHOLDER - (implemented|written) in PHASE \d+")


def _files():
    for path in ROOT.rglob("*"):
        rel = path.relative_to(ROOT)
        if any(part in SKIP_DIRS for part in rel.parts) or not path.is_file():
            continue
        if path.suffix in SUFFIXES or path.name in {"Dockerfile", "docker-compose.yml"}:
            yield rel, path


def test_no_placeholder_stubs_remain():
    offenders = [
        str(rel)
        for rel, path in _files()
        if rel.name != "test_repository_hygiene.py"
        and STUB.search(path.read_text(encoding="utf-8", errors="ignore"))
    ]
    assert offenders == [], f"placeholder stubs: {offenders}"


def test_versions_agree():
    """One version for the release: backend package, API settings, frontend package."""
    import json
    import tomllib

    from app.core.config import Settings

    backend = tomllib.loads((BACKEND_DIR / "pyproject.toml").read_text())["project"]["version"]
    frontend = json.loads((ROOT / "frontend" / "package.json").read_text())["version"]
    settings = Settings.model_fields["app_version"].default
    assert backend == frontend == settings


def test_release_documents_exist_and_are_linked():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for doc in ("RELEASE_READINESS.md", "DEPLOYMENT.md", "BACKUP_AND_RECOVERY.md"):
        assert (ROOT / doc).is_file(), doc
        assert doc in readme, f"README does not link {doc}"


def test_every_adr_is_indexed():
    adr_dir = ROOT / "docs" / "architecture"
    index = (adr_dir / "README.md").read_text(encoding="utf-8")
    for adr in sorted(adr_dir.glob("ADR-*.md")):
        number = adr.stem.split("-")[1]
        assert f"[{number}](ADR-{number}.md)" in index, f"{adr.name} missing from the ADR index"
