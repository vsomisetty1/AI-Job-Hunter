// Package status pill.
import { Badge } from "@/components/ui/Badge";
import type { PackageStatus } from "@/types";

const TONE: Record<PackageStatus, "neutral" | "green" | "amber" | "red" | "indigo"> = {
  generating: "amber",
  generated: "indigo",
  reviewed: "indigo",
  approved: "green",
  submitted: "green",
  rejected: "red",
  failed: "red",
  superseded: "neutral",
};

const LABEL: Record<PackageStatus, string> = {
  generating: "generating…",
  generated: "ready for review",
  reviewed: "reviewed",
  approved: "approved",
  submitted: "submitted",
  rejected: "rejected",
  failed: "failed",
  superseded: "superseded",
};

export function PackageStatusBadge({ status }: { status: PackageStatus }) {
  return <Badge tone={TONE[status]}>{LABEL[status]}</Badge>;
}
