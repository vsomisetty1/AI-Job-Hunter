"""Agent 3: job deduplication (pure logic, no I/O).

Three layers, applied in order to every posting of a crawled board:

1. Same board posting (company + source job id): update if its content
   changed, otherwise just mark it seen. Repeats inside one response are
   skipped.
2. Same URL as a *different* posting (any company): skipped. URLs are unique
   in the database, and two postings at one URL are the same job.
3. Same fingerprint (normalized company + title + location) as an active job
   of a *different* company row, i.e. the same employer tracked on two
   platforms: skipped as a cross-board duplicate. Identical titles within
   one company are kept: employers legitimately post several openings.
"""

import re
import unicodedata
import uuid
from dataclasses import dataclass
from typing import Literal

from app.schemas.job import NormalizedJob
from app.utils.hashing import hash_json, sha256_hex

_LEGAL = re.compile(
    r"\b(inc|incorporated|llc|ltd|limited|corp|corporation|co|company|gmbh|plc|sa|ag|bv|oy|ab"
    r"|pty|technologies|technology|labs|hq|group|holdings)\b\.?",
)
_TITLE_ALIASES = [
    (r"\bsr\b\.?", "senior"),
    (r"\bjr\b\.?", "junior"),
    (r"\beng\b\.?", "engineer"),
    (r"\bmgr\b\.?", "manager"),
    (r"&", " and "),
]


def _fold(text: str | None) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    return text


def normalize_company(name: str | None) -> str:
    text = _LEGAL.sub(" ", _fold(name))
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def normalize_title(title: str | None) -> str:
    text = _fold(title)
    for pattern, repl in _TITLE_ALIASES:
        text = re.sub(pattern, repl, text)
    text = re.sub(r"\([^)]*\)", " ", text)  # "(Remote)", "(m/f/d)"
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def normalize_location(location: str | None) -> str:
    text = re.sub(r"[^a-z0-9;]+", " ", _fold(location))
    parts = sorted({p.strip() for p in text.split(";") if p.strip()})
    return ";".join(parts)


def dedup_key(company_name: str, title: str, location: str | None) -> str:
    """Cross-board fingerprint (sha256 hex)."""
    return sha256_hex(
        f"{normalize_company(company_name)}|{normalize_title(title)}|{normalize_location(location)}"
    )


def content_hash(job: NormalizedJob) -> str:
    """Hash of everything shown about a job (not the raw payload)."""
    return hash_json(job.model_dump(mode="json", exclude={"raw"}))


Action = Literal["insert", "update", "unchanged", "skip"]


@dataclass(frozen=True)
class Existing:
    id: uuid.UUID
    content_hash: str | None
    status: str


@dataclass(frozen=True)
class Decision:
    job: NormalizedJob
    action: Action
    existing_id: uuid.UUID | None = None
    reason: str | None = None
    revive: bool = False  # an expired job reappeared on its board


def decide(
    jobs: list[NormalizedJob],
    *,
    existing: dict[str, Existing],
    url_owners: dict[str, tuple[uuid.UUID, str]],
    fingerprint_owners: dict[str, uuid.UUID],
) -> list[Decision]:
    """Classify every job of one board.

    existing:            this company's jobs by source job id
    url_owners:          url -> (job id, source job id) for URLs already stored
    fingerprint_owners:  dedup_key -> job id of active jobs at OTHER companies
    """
    out: list[Decision] = []
    seen_ids: set[str] = set()
    seen_urls: set[str] = set()
    for job in jobs:
        if job.source_job_id in seen_ids:
            out.append(Decision(job, "skip", reason="repeated in the board response"))
            continue
        seen_ids.add(job.source_job_id)

        current = existing.get(job.source_job_id)
        owner = url_owners.get(job.url)
        if job.url in seen_urls:
            out.append(Decision(job, "skip", reason="URL repeated in the board response"))
            continue
        if owner and (current is None or owner[0] != current.id):
            out.append(
                Decision(
                    job, "skip", existing_id=owner[0], reason="URL already belongs to another job"
                )
            )
            continue
        seen_urls.add(job.url)

        if current is not None:
            revive = current.status == "expired"
            changed = current.content_hash != content_hash(job)
            action: Action = "update" if (changed or revive) else "unchanged"
            out.append(Decision(job, action, existing_id=current.id, revive=revive))
            continue

        twin = fingerprint_owners.get(dedup_key(job.company_name, job.title, job.location))
        if twin is not None:
            out.append(
                Decision(
                    job, "skip", existing_id=twin, reason="same job already found on another board"
                )
            )
            continue
        out.append(Decision(job, "insert"))
    return out
