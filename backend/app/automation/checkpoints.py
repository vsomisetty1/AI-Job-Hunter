"""Checkpoints: what a run has done so far, so it can be resumed.

ATS forms keep no server-side draft, so "resuming" means reopening the form
and replaying the stored decisions: the field outcomes (what went where and
why), the uploads, and the user's edits, which always win. Replaying is
deterministic, so a resumed run fills exactly what the user already saw,
plus anything they edited.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

CHECKPOINT_VERSION = 1


@dataclass
class Checkpoint:
    step: str = "queued"
    url: str | None = None
    fields: list[dict[str, Any]] = field(default_factory=list)  # FieldOutcome.as_dict()
    uploads: dict[str, dict[str, Any]] = field(default_factory=dict)  # resume/cover_letter
    form_signature: str | None = None  # field keys seen: detects a changed form on resume
    attempt: int = 0
    at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def as_json(self) -> dict[str, Any]:
        return {
            "version": CHECKPOINT_VERSION,
            "step": self.step,
            "url": self.url,
            "fields": self.fields,
            "uploads": self.uploads,
            "form_signature": self.form_signature,
            "attempt": self.attempt,
            "at": self.at,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any] | None) -> Checkpoint:
        data = data or {}
        if data.get("version") not in (None, CHECKPOINT_VERSION):
            return cls()  # an older layout: start afresh rather than misread it
        return cls(
            step=str(data.get("step") or "queued"),
            url=data.get("url"),
            fields=list(data.get("fields") or []),
            uploads=dict(data.get("uploads") or {}),
            form_signature=data.get("form_signature"),
            attempt=int(data.get("attempt") or 0),
            at=str(data.get("at") or datetime.now(UTC).isoformat()),
        )

    def previous_value(self, key: str) -> dict[str, Any] | None:
        return next((f for f in self.fields if f.get("key") == key), None)


def form_signature(keys: list[str]) -> str:
    """Order-insensitive fingerprint of a form's fields."""
    import hashlib

    return hashlib.sha256("\n".join(sorted(keys)).encode()).hexdigest()[:16]
