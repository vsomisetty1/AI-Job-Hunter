"use client";

// Failure recovery: what went wrong, what to do, and the actions that help.
import { useState } from "react";

import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { automationApi } from "@/lib/api/applications";
import { errorMessage } from "@/lib/api/client";
import { packagesApi } from "@/lib/api/packages";
import type { SubmissionSummary } from "@/types";

const KIND_LABEL: Record<string, string> = {
  browser_crash: "Browser crashed",
  timeout: "Timed out",
  network: "Network error",
  upload_failed: "Upload failed",
  validation_failed: "Form validation failed",
  ats_changed: "Form layout changed",
  captcha: "CAPTCHA",
  job_closed: "Job closed",
  unconfirmed: "Not confirmed",
  interrupted: "Interrupted",
  internal: "Unexpected error",
};

export function FailureRecovery({
  submission,
  hint,
  onChange,
  compact = false,
}: {
  submission: SubmissionSummary;
  hint?: string | null;
  onChange: () => void;
  compact?: boolean;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [applied, setApplied] = useState(false);

  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
      onChange();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const kind = submission.error_kind ?? "internal";
  // After an unconfirmed or interrupted submit the application may have gone through.
  const maybeSent = kind === "unconfirmed" || (kind === "interrupted" && submission.confirmed_at !== null);
  const canRetry = kind !== "job_closed";

  return (
    <div className="space-y-2" data-testid="failure-recovery">
      <Alert tone="error">
        <strong>{KIND_LABEL[kind] ?? kind}:</strong> {submission.error}
        {!compact && hint && <div className="mt-1">{hint}</div>}
      </Alert>
      {maybeSent && (
        <Alert tone="warning">
          This application may have been sent. Check your email or the company&apos;s portal before retrying, so
          you do not apply twice.
        </Alert>
      )}
      {error && <Alert tone="error">{error}</Alert>}
      <div className="flex flex-wrap gap-2">
        {canRetry && (
          <Button disabled={busy} onClick={() => act(() => automationApi.retry(submission.id))}>
            {maybeSent ? "Retry anyway" : "Retry"}
          </Button>
        )}
        <Button variant="secondary" disabled={busy} onClick={() => act(() => automationApi.cancel(submission.id))}>
          Dismiss
        </Button>
        {maybeSent && submission.package_id && !applied && (
          <Button
            variant="secondary"
            disabled={busy}
            onClick={() =>
              act(async () => {
                await packagesApi.markSubmitted(submission.package_id as string);
                setApplied(true);
              })
            }
          >
            It went through: mark as applied
          </Button>
        )}
      </div>
    </div>
  );
}
