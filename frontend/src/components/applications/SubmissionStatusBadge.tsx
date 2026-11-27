// Submission (automation run) status pill.
import { Badge } from "@/components/ui/Badge";
import type { SubmissionStatus } from "@/types";

const TONE: Record<SubmissionStatus, "neutral" | "green" | "amber" | "red" | "indigo"> = {
  queued: "neutral",
  in_progress: "amber",
  waiting_for_review: "indigo",
  submitting: "amber",
  submitted: "green",
  failed: "red",
  cancelled: "neutral",
};

export const STATUS_LABEL: Record<SubmissionStatus, string> = {
  queued: "queued",
  in_progress: "filling the form…",
  waiting_for_review: "waiting for your review",
  submitting: "submitting…",
  submitted: "submitted",
  failed: "failed",
  cancelled: "cancelled",
};

export function SubmissionStatusBadge({ status }: { status: SubmissionStatus }) {
  return <Badge tone={TONE[status]}>{STATUS_LABEL[status]}</Badge>;
}
