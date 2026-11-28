"""Submission rows as API responses (summary, detail with editable fields)."""

import logging
import uuid

from app.automation.recovery import hint
from app.repositories.automation_repository import (
    SubmissionRow,
)
from app.schemas.automation import (
    EditableField,
    Screenshot,
    SubmissionDetail,
    SubmissionSummary,
)

logger = logging.getLogger(__name__)


def submission_summary(row: SubmissionRow, *, live: bool) -> SubmissionSummary:
    """`live`: the filled form is still open in the browser (SessionRegistry)."""
    s = row.submission
    review = s.review or {}
    return SubmissionSummary(
        id=s.id,
        application_id=s.application_id,
        package_id=s.package_id,
        job_id=row.job_id,
        job_title=row.job_title,
        company_name=row.company_name,
        job_status=row.job_status,
        platform=s.platform,
        apply_url=s.apply_url,
        mode="APPROVAL_MODE",
        status=s.status,
        step=s.step,
        attempts=s.attempts,
        error=s.error,
        error_kind=s.error_kind,
        live=s.status == "waiting_for_review" and live,
        ready=review.get("ready") if review else None,
        missing_count=len(review.get("missing", [])),
        problem_count=len(review.get("problems", [])),
        queued_at=s.queued_at,
        started_at=s.started_at,
        review_ready_at=s.review_ready_at,
        confirmed_at=s.confirmed_at,
        submitted_at=s.submitted_at,
        failed_at=s.failed_at,
        cancelled_at=s.cancelled_at,
        updated_at=s.updated_at,
    )


def submission_detail(row: SubmissionRow, *, live: bool) -> SubmissionDetail:
    s = row.submission
    summary = submission_summary(row, live=live)
    review = s.review or {}
    fields = (s.checkpoint or {}).get("fields", [])
    editable = [
        EditableField(
            key=str(f.get("key") or ""),
            label=str(f.get("label") or ""),
            kind=str(f.get("kind") or ""),
            required=bool(f.get("required", False)),
            status=str(f.get("status") or ""),
            value=s.edits.get(str(f.get("key") or ""), f.get("value") or ""),
            reason=str(f.get("reason") or ""),
            options=[str(o) for o in f.get("options") or []],
            edited=f.get("key") in s.edits,
        )
        for f in fields
        if f.get("kind") != "file" and not f.get("sensitive")
    ]
    return SubmissionDetail(
        **summary.model_dump(),
        review=review,
        edits=s.edits,
        checkpoint=s.checkpoint,
        screenshots=[
            Screenshot(
                index=i + 1,
                step=str(x.get("step", "")),
                label=str(x.get("label", "")),
                at=x.get("at"),
            )  # fmt: skip
            for i, x in enumerate(s.screenshots)
        ],
        confirmation_text=s.confirmation_text,
        recovery_hint=hint(s.error_kind) if s.error_kind else None,
        editable_fields=editable,
    )


def latest_per_application(rows: list[SubmissionRow]) -> list[SubmissionRow]:
    seen: set[uuid.UUID] = set()
    out = []
    for r in rows:  # newest first
        if r.submission.application_id not in seen:
            seen.add(r.submission.application_id)
            out.append(r)
    return out
